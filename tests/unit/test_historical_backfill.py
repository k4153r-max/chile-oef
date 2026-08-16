from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from chile_oef.ingestion.historical_backfill import plan_time_partitions


def _event_count_fn(event_times: list[datetime]):
    async def count_fn(start: datetime, end: datetime) -> int:
        return sum(1 for t in event_times if start <= t < end)

    return count_fn


def _assert_full_coverage_no_gaps_no_overlaps(
    slices: list[tuple[datetime, datetime]], start: datetime, end: datetime
) -> None:
    ordered = sorted(slices, key=lambda s: s[0])
    assert ordered[0][0] == start
    assert ordered[-1][1] == end
    for (_, prev_end), (next_start, _) in zip(ordered, ordered[1:], strict=False):
        assert prev_end == next_start


@pytest.mark.asyncio
async def test_returns_single_slice_when_under_threshold() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2020, 2, 1, tzinfo=UTC)
    slices = await plan_time_partitions(
        _event_count_fn([]), start, end, max_results=1000, min_slice=timedelta(hours=1)
    )
    assert slices == [(start, end)]


@pytest.mark.asyncio
async def test_bisects_uniform_high_density_until_every_leaf_is_under_threshold() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2020, 1, 8, tzinfo=UTC)
    rng = np.random.default_rng(0)
    total_seconds = (end - start).total_seconds()
    event_times = sorted(
        start + timedelta(seconds=float(s)) for s in rng.uniform(0, total_seconds, size=50_000)
    )
    slices = await plan_time_partitions(
        _event_count_fn(event_times), start, end, max_results=1000, min_slice=timedelta(minutes=1)
    )
    _assert_full_coverage_no_gaps_no_overlaps(slices, start, end)
    count_fn = _event_count_fn(event_times)
    for slice_start, slice_end in slices:
        count = await count_fn(slice_start, slice_end)
        assert count <= 1000
    # Sanity: partitioning actually happened (not one giant slice).
    assert len(slices) > 10


@pytest.mark.asyncio
async def test_adapts_finer_partitioning_to_a_dense_sub_region() -> None:
    """A swarm concentrated in the first quarter of the range should force
    much finer slicing there than in the quiet remainder -- not a uniform
    grid of slices regardless of where the events actually are.
    """
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2020, 1, 5, tzinfo=UTC)
    swarm_end = start + (end - start) / 4
    rng = np.random.default_rng(1)
    swarm_seconds = (swarm_end - start).total_seconds()
    swarm_times = sorted(
        start + timedelta(seconds=float(s)) for s in rng.uniform(0, swarm_seconds, size=20_000)
    )
    slices = await plan_time_partitions(
        _event_count_fn(swarm_times), start, end, max_results=500, min_slice=timedelta(minutes=1)
    )
    _assert_full_coverage_no_gaps_no_overlaps(slices, start, end)
    swarm_slices = [s for s in slices if s[1] <= swarm_end]
    quiet_slices = [s for s in slices if s[0] >= swarm_end]
    assert len(swarm_slices) > len(quiet_slices)
    assert len(quiet_slices) <= 2


@pytest.mark.asyncio
async def test_raises_when_minimum_granularity_still_exceeds_threshold() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2020, 1, 1, 2, tzinfo=UTC)

    async def always_over_threshold(_start: datetime, _end: datetime) -> int:
        return 999_999

    with pytest.raises(RuntimeError, match="not partitionable further"):
        await plan_time_partitions(
            always_over_threshold, start, end, max_results=1000, min_slice=timedelta(minutes=30)
        )


@pytest.mark.asyncio
async def test_rejects_start_not_before_end() -> None:
    moment = datetime(2020, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="start must be before end"):
        await plan_time_partitions(
            _event_count_fn([]), moment, moment, max_results=1000, min_slice=timedelta(hours=1)
        )
