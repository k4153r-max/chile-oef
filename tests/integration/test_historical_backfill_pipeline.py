import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import EventRevision, HistoricalBackfillSlice
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.historical_backfill import (
    BackfillBounds,
    BackfillPolicy,
    run_usgs_historical_backfill,
)
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import sync_source_registry

BOUNDS = BackfillBounds(
    min_latitude=-60.0, max_latitude=-15.0, min_longitude=-82.0, max_longitude=-62.0
)


@dataclass
class FakeUsgsSliceAdapter:
    events: list[NormalizedEvent]
    fail: bool = False
    source_id: str = "usgs_comcat"
    parser_version: str = "fake-fdsn-v1"

    async def count(self) -> int:
        return len(self.events)

    async def fetch(self) -> FetchedArtifact:
        if self.fail:
            raise RuntimeError("simulated transient FDSN failure")
        content = json.dumps(sorted(e.source_event_id for e in self.events)).encode()
        return FetchedArtifact(
            source_id=self.source_id,
            source_url=f"fake://slice?n={len(self.events)}",
            retrieved_at=datetime.now(UTC),
            content=content,
            media_type="application/json",
            http_status=200,
        )

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        return self.events


@dataclass
class FakeAdapterFactory:
    all_events: list[NormalizedEvent]
    poison_event_id: str | None = None
    calls: list[tuple[datetime, datetime]] = field(default_factory=list)

    def __call__(self, start: datetime, end: datetime) -> FakeUsgsSliceAdapter:
        self.calls.append((start, end))
        subset = [e for e in self.all_events if start <= e.event_time < end]
        fail = self.poison_event_id is not None and any(
            e.source_event_id == self.poison_event_id for e in subset
        )
        return FakeUsgsSliceAdapter(events=subset, fail=fail)


def _synthetic_events(window_start: datetime, count: int) -> list[NormalizedEvent]:
    events = []
    for index in range(count):
        event_time = window_start + timedelta(hours=index * 7)
        events.append(
            NormalizedEvent(
                source_id="usgs_comcat",
                source_event_id=f"bf-{index}",
                event_time=event_time,
                received_at=event_time + timedelta(minutes=5),
                available_at=event_time + timedelta(minutes=5),
                latitude=-33.0,
                longitude=-71.0,
                depth_km=15.0,
                depth_uncertainty_km=5.0,
                magnitude=4.0,
                magnitude_type="mb",
                source_payload={"id": f"bf-{index}"},
                parser_version="fake-fdsn-v1",
            )
        )
    return events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_ingests_all_slices_and_is_resumable(
    postgis_engine: Engine, tmp_path: Path
) -> None:
    window_start = datetime(2020, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=30)
    events = _synthetic_events(window_start, count=40)

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(session, load_source_registry(Path("config/source-registry.yaml")))

        factory = FakeAdapterFactory(all_events=events)
        summary = await run_usgs_historical_backfill(
            session,
            RawArchive(tmp_path / "raw"),
            start_time=window_start,
            end_time=window_end,
            bounds=BOUNDS,
            policy=BackfillPolicy(
                max_results_per_slice=5,
                min_slice=timedelta(hours=1),
                request_delay_seconds=0.0,
                retry_backoff_seconds=0.0,
            ),
            adapter_factory=factory,
            sleep_fn=lambda _seconds: _immediate(),
        )

        assert summary.failed_slices == []
        assert summary.total_slices > 1, "40 events at max 5/slice must force real partitioning"
        assert summary.succeeded_slices == summary.total_slices
        assert summary.skipped_already_done_slices == 0
        assert summary.total_events_seen == len(events)

        revision_count = session.scalar(select(func.count()).select_from(EventRevision))
        assert revision_count == len(events)

        slice_rows = list(
            session.scalars(
                select(HistoricalBackfillSlice).where(
                    HistoricalBackfillSlice.source_id == "usgs_comcat"
                )
            )
        )
        assert len(slice_rows) == summary.total_slices
        assert all(row.status == "succeeded" for row in slice_rows)

        # Re-running the identical backfill must skip every slice already
        # marked succeeded, not re-fetch or re-insert anything.
        second_factory = FakeAdapterFactory(all_events=events)
        second_summary = await run_usgs_historical_backfill(
            session,
            RawArchive(tmp_path / "raw"),
            start_time=window_start,
            end_time=window_end,
            bounds=BOUNDS,
            policy=BackfillPolicy(
                max_results_per_slice=5,
                min_slice=timedelta(hours=1),
                request_delay_seconds=0.0,
                retry_backoff_seconds=0.0,
            ),
            adapter_factory=second_factory,
            sleep_fn=lambda _seconds: _immediate(),
        )
        assert second_summary.succeeded_slices == 0
        assert second_summary.skipped_already_done_slices == second_summary.total_slices
        revision_count_after = session.scalar(select(func.count()).select_from(EventRevision))
        assert revision_count_after == len(events)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_backfill_isolates_a_persistently_failing_slice(
    postgis_engine: Engine, tmp_path: Path
) -> None:
    """One slice that fails on every attempt (a real, non-transient
    problem) must be recorded as failed and reported -- without aborting
    ingestion of every other slice in the run.
    """
    window_start = datetime(2021, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=30)
    events = _synthetic_events(window_start, count=40)
    poison_id = events[len(events) // 2].source_event_id

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(session, load_source_registry(Path("config/source-registry.yaml")))

        factory = FakeAdapterFactory(all_events=events, poison_event_id=poison_id)
        summary = await run_usgs_historical_backfill(
            session,
            RawArchive(tmp_path / "raw"),
            start_time=window_start,
            end_time=window_end,
            bounds=BOUNDS,
            policy=BackfillPolicy(
                max_results_per_slice=5,
                min_slice=timedelta(hours=1),
                max_retries=2,
                request_delay_seconds=0.0,
                retry_backoff_seconds=0.0,
            ),
            adapter_factory=factory,
            sleep_fn=lambda _seconds: _immediate(),
        )

        assert len(summary.failed_slices) == 1
        assert summary.succeeded_slices == summary.total_slices - 1
        failed_start, failed_end, failed_message = summary.failed_slices[0]
        poison_slice_event_count = sum(
            1 for e in events if failed_start <= e.event_time < failed_end
        )
        assert poison_slice_event_count >= 1
        assert summary.total_events_seen == len(events) - poison_slice_event_count
        assert "simulated transient FDSN failure" in failed_message

        failed_rows = list(
            session.scalars(
                select(HistoricalBackfillSlice).where(HistoricalBackfillSlice.status == "failed")
            )
        )
        assert len(failed_rows) == 1
        assert "simulated transient FDSN failure" in failed_rows[0].error_message


async def _immediate() -> None:
    return None
