"""Bulk historical USGS FDSN ingestion, orchestrating the bounded, single-
slice `UsgsFdsnAdapter` (src/chile_oef/ingestion/sources/usgs_fdsn.py)
over a long time range that would otherwise exceed the service's 20,000-
result cap. This is the real historical backfill the rest of this project
needs before any evaluation (Phase 6, `chile_oef.evaluation.replay`) can
honestly be called prospective against actual Chilean seismicity, rather
than the synthetic catalogs every estimator has been validated against so
far -- see docs/PROJECT_STATE.md's Phase 6 section.

Two properties this module is built around:

- resumable: a long backfill (potentially thousands of requests over
  minutes to hours) can be interrupted and re-run without re-fetching
  slices already ingested successfully -- tracked in a dedicated
  `HistoricalBackfillSlice` row per slice, not by fragile URL
  string-matching against `IngestionRun.request_url`;
- one bad slice does not abort the whole run: transient failures are
  retried with backoff, and a slice that still fails after retries is
  recorded as failed and the backfill continues, reporting exactly which
  slices need a manual retry rather than silently losing that range or
  crashing partway through a multi-hour run.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from chile_oef.db.models import HistoricalBackfillSlice
from chile_oef.ingestion.base import EventSourceAdapter
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.service import IngestionService
from chile_oef.ingestion.sources.usgs_fdsn import UsgsFdsnAdapter


@dataclass(frozen=True)
class BackfillPolicy:
    version: int = 1
    # Below the FDSN service's real 20,000-result cap, leaving headroom for
    # events that land between this slice's count() check and its fetch()
    # (only relevant for slices whose end_time is close to "now").
    max_results_per_slice: int = 15_000
    min_slice: timedelta = timedelta(hours=6)
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    request_delay_seconds: float = 1.0


class _CountFn(Protocol):
    async def __call__(self, start: datetime, end: datetime) -> int: ...


async def plan_time_partitions(
    count_fn: _CountFn,
    start: datetime,
    end: datetime,
    *,
    max_results: int,
    min_slice: timedelta,
) -> list[tuple[datetime, datetime]]:
    """Recursively bisect `[start, end)` until every leaf slice's event
    count is at or below `max_results`. `count_fn` is injected (rather
    than this function constructing its own adapter) so the partitioning
    logic itself -- the part with real correctness requirements (full
    coverage, no gaps or overlaps, termination) -- can be unit tested
    against a synthetic density function with no network or database
    involved.

    Raises if a slice still exceeds `max_results` at `min_slice`
    granularity: that is not partitionable further by this strategy and
    needs a human to look at it (an anomalous swarm, or `min_slice` set
    too coarse for the region), not a silent truncation of real events.
    """
    if start >= end:
        raise ValueError("start must be before end")
    count = await count_fn(start, end)
    if count <= max_results:
        return [(start, end)]
    if end - start <= min_slice:
        raise RuntimeError(
            f"slice {start.isoformat()}..{end.isoformat()} still has {count} "
            f"events at the minimum granularity ({min_slice}); this is not "
            "partitionable further and needs manual investigation, not a "
            "silently truncated fetch"
        )
    midpoint = start + (end - start) / 2
    left = await plan_time_partitions(
        count_fn, start, midpoint, max_results=max_results, min_slice=min_slice
    )
    right = await plan_time_partitions(
        count_fn, midpoint, end, max_results=max_results, min_slice=min_slice
    )
    return left + right


@dataclass(frozen=True)
class BackfillBounds:
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float


@dataclass(frozen=True)
class BackfillSummary:
    total_slices: int
    succeeded_slices: int
    skipped_already_done_slices: int
    failed_slices: list[tuple[datetime, datetime, str]] = field(default_factory=list)
    total_events_seen: int = 0
    total_revisions_inserted: int = 0


AdapterFactory = Callable[[datetime, datetime], EventSourceAdapter]


def _default_adapter_factory(
    *,
    bounds: BackfillBounds,
    min_magnitude: float | None,
    timeout_seconds: float,
    user_agent: str,
) -> AdapterFactory:
    def factory(start: datetime, end: datetime) -> UsgsFdsnAdapter:
        return UsgsFdsnAdapter(
            start_time=start,
            end_time=end,
            min_latitude=bounds.min_latitude,
            max_latitude=bounds.max_latitude,
            min_longitude=bounds.min_longitude,
            max_longitude=bounds.max_longitude,
            min_magnitude=min_magnitude,
            timeout_seconds=timeout_seconds,
            user_agent=user_agent,
        )

    return factory


async def _count_via_adapter_factory(
    adapter_factory: AdapterFactory, start: datetime, end: datetime
) -> int:
    adapter = adapter_factory(start, end)
    return await adapter.count()  # type: ignore[attr-defined]


def _existing_slice(
    session: Session,
    *,
    source_id: str,
    start: datetime,
    end: datetime,
    min_magnitude: float | None,
    bounds: BackfillBounds,
) -> HistoricalBackfillSlice | None:
    return session.scalar(
        select(HistoricalBackfillSlice).where(
            HistoricalBackfillSlice.source_id == source_id,
            HistoricalBackfillSlice.start_time == start,
            HistoricalBackfillSlice.end_time == end,
            HistoricalBackfillSlice.min_magnitude == min_magnitude,
            HistoricalBackfillSlice.min_latitude == bounds.min_latitude,
            HistoricalBackfillSlice.max_latitude == bounds.max_latitude,
            HistoricalBackfillSlice.min_longitude == bounds.min_longitude,
            HistoricalBackfillSlice.max_longitude == bounds.max_longitude,
        )
    )


async def run_usgs_historical_backfill(
    session: Session,
    raw_archive: RawArchive,
    *,
    source_id: str = "usgs_comcat",
    start_time: datetime,
    end_time: datetime,
    bounds: BackfillBounds,
    min_magnitude: float | None = None,
    timeout_seconds: float = 60.0,
    user_agent: str = "CHILE-OEF/0.1 research-platform",
    policy: BackfillPolicy | None = None,
    adapter_factory: AdapterFactory | None = None,
    sleep_fn: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> BackfillSummary:
    if start_time.tzinfo is None or end_time.tzinfo is None:
        raise ValueError("start_time and end_time must be timezone-aware")
    if start_time >= end_time:
        raise ValueError("start_time must be before end_time")

    policy = policy or BackfillPolicy()
    factory = adapter_factory or _default_adapter_factory(
        bounds=bounds,
        min_magnitude=min_magnitude,
        timeout_seconds=timeout_seconds,
        user_agent=user_agent,
    )

    async def count_fn(start: datetime, end: datetime) -> int:
        return await _count_via_adapter_factory(factory, start, end)

    slices = await plan_time_partitions(
        count_fn,
        start_time,
        end_time,
        max_results=policy.max_results_per_slice,
        min_slice=policy.min_slice,
    )

    ingestion_service = IngestionService(session, raw_archive)
    succeeded = 0
    skipped = 0
    failed: list[tuple[datetime, datetime, str]] = []
    total_events = 0
    total_inserted = 0

    for slice_start, slice_end in slices:
        existing = _existing_slice(
            session,
            source_id=source_id,
            start=slice_start,
            end=slice_end,
            min_magnitude=min_magnitude,
            bounds=bounds,
        )
        if existing is not None and existing.status == "succeeded":
            skipped += 1
            continue

        last_error: Exception | None = None
        for attempt in range(1, policy.max_retries + 1):
            try:
                adapter = factory(slice_start, slice_end)
                result = await ingestion_service.run(adapter)
                succeeded += 1
                total_events += result.records_seen
                total_inserted += result.revisions_inserted
                slice_row = existing or HistoricalBackfillSlice(
                    source_id=source_id,
                    start_time=slice_start,
                    end_time=slice_end,
                    min_magnitude=min_magnitude,
                    min_latitude=bounds.min_latitude,
                    max_latitude=bounds.max_latitude,
                    min_longitude=bounds.min_longitude,
                    max_longitude=bounds.max_longitude,
                )
                slice_row.status = "succeeded"
                slice_row.ingestion_run_id = result.run_id
                slice_row.event_count = result.records_seen
                slice_row.error_message = None
                slice_row.attempted_at = datetime.now(UTC)
                session.add(slice_row)
                session.commit()
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001 -- recorded, not swallowed
                last_error = exc
                if attempt < policy.max_retries:
                    await sleep_fn(policy.retry_backoff_seconds * attempt)
        if last_error is not None:
            failed.append((slice_start, slice_end, str(last_error)[:2000]))
            slice_row = existing or HistoricalBackfillSlice(
                source_id=source_id,
                start_time=slice_start,
                end_time=slice_end,
                min_magnitude=min_magnitude,
                min_latitude=bounds.min_latitude,
                max_latitude=bounds.max_latitude,
                min_longitude=bounds.min_longitude,
                max_longitude=bounds.max_longitude,
            )
            slice_row.status = "failed"
            slice_row.error_message = str(last_error)[:2000]
            slice_row.attempted_at = datetime.now(UTC)
            session.add(slice_row)
            session.commit()
        await sleep_fn(policy.request_delay_seconds)

    return BackfillSummary(
        total_slices=len(slices),
        succeeded_slices=succeeded,
        skipped_already_done_slices=skipped,
        failed_slices=failed,
        total_events_seen=total_events,
        total_revisions_inserted=total_inserted,
    )
