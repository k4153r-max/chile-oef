import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import CompletenessEstimate
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.etas import EtasPolicy
from chile_oef.seismicity.ias import IasPolicy
from chile_oef.seismicity.service import IasEstimationService, TemporalEtasService


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/ias-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"ias-fixture",
            media_type="application/octet-stream",
            http_status=200,
        )

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        return self.events


def _event(
    *, source_event_id: str, event_time: datetime, available_at: datetime, magnitude: float
) -> NormalizedEvent:
    return NormalizedEvent(
        source_id="usgs_comcat",
        source_event_id=source_event_id,
        event_time=event_time,
        received_at=available_at,
        available_at=available_at,
        latitude=-33.0,
        longitude=-71.0,
        depth_km=20.0,
        depth_uncertainty_km=5.0,
        magnitude=magnitude,
        magnitude_type="ml",
        source_payload={"id": source_event_id},
        parser_version="fixture-v1",
    )


def _integral_rate(c: float, p: float, d: float) -> float:
    if d <= 0:
        return 0.0
    if abs(p - 1.0) < 1e-8:
        return math.log(d + c) - math.log(c)
    return ((d + c) ** (1.0 - p) - c ** (1.0 - p)) / (1.0 - p)


def _simulate_light_etas_days(
    *, mu: float, k0: float, c: float, p: float, duration_days: float, seed: int
) -> list[float]:
    rng = np.random.default_rng(seed)
    background_count = rng.poisson(mu * duration_days)
    times: list[float] = []
    queue: list[float] = []
    for _ in range(background_count):
        t0 = float(rng.uniform(0.0, duration_days))
        times.append(t0)
        queue.append(t0)
    while queue:
        if len(times) > 5000:
            raise RuntimeError("synthetic catalog exploded")
        parent_time = queue.pop()
        remaining = duration_days - parent_time
        if remaining <= 0:
            continue
        total_expected = k0 * _integral_rate(c, p, remaining)
        n = rng.poisson(total_expected)
        if n == 0:
            continue
        u = rng.uniform(0.0, total_expected, size=n)
        base = c ** (1.0 - p) + u * (1.0 - p) / k0
        offsets = base ** (1.0 / (1.0 - p)) - c
        for offset in offsets:
            child_time = parent_time + float(offset)
            if child_time > duration_days:
                continue
            times.append(child_time)
            queue.append(child_time)
    times.sort()
    return times


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ias_persists_through_the_service_chained_off_temporal_etas(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: ingest a real catalog, declare Mc, fit temporal ETAS,
    then evaluate IAS against that specific fit at a specific instant.
    Confirms the provenance FK and persisted fields, including that
    evaluation_start_time/evaluation_end_time are consistent with the
    requested evaluation instant and the policy's window length.
    """
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    duration_days = 250.0
    window_end = window_start + timedelta(days=duration_days)
    as_of = window_end
    mc = 3.0

    times_days = _simulate_light_etas_days(
        mu=1.0, k0=0.04, c=0.1, p=1.2, duration_days=duration_days, seed=5
    )
    assert len(times_days) >= 100, "synthetic catalog too small for this seed"

    events = [
        _event(
            source_event_id=f"ias-{index}",
            event_time=window_start + timedelta(days=offset),
            available_at=window_start + timedelta(days=offset, minutes=5),
            magnitude=3.5,
        )
        for index, offset in enumerate(times_days)
    ]

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        mc_record = CompletenessEstimate(
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
            method_version="fixture",
            role="diagnostic",
            calibration_status="fixture",
            event_count=len(events),
            support_state="supported",
            mc_value=mc,
            bin_width_magnitude=0.1,
            catalog_as_of=as_of,
            diagnostics_json={},
        )
        session.add(mc_record)
        session.commit()

        etas_record = TemporalEtasService(
            session, policy=EtasPolicy(restarts=1, minimum_events=100)
        ).estimate_for_completeness_estimate(mc_record.id)

        if not etas_record.converged:
            pytest.skip("temporal ETAS did not converge on this seed with a single restart")

        evaluation_end_at = window_start + timedelta(days=duration_days - 5.0)
        ias_policy = IasPolicy(evaluation_window_days=7.0, minimum_historical_windows=10)
        ias_record = IasEstimationService(
            session, policy=ias_policy
        ).estimate_for_temporal_etas_estimate(etas_record.id, evaluation_end_at=evaluation_end_at)

        assert ias_record.temporal_etas_estimate_id == etas_record.id
        assert ias_record.evaluation_end_time == evaluation_end_at
        assert ias_record.evaluation_start_time == evaluation_end_at - timedelta(days=7.0)
        assert ias_record.evaluation_window_days == pytest.approx(7.0)
        assert ias_record.calibration_status == "uncalibrated_anomaly_index"
        if ias_record.support_state == "estimable":
            assert ias_record.ias_score is not None
            assert 0.0 <= ias_record.ias_score <= 100.0
        else:
            assert ias_record.ias_score is None
        assert ias_record.id is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ias_refuses_a_non_converged_temporal_etas_estimate(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=10)

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        mc_record = CompletenessEstimate(
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
            method_version="fixture",
            role="diagnostic",
            calibration_status="fixture",
            event_count=0,
            support_state="not_estimable",
            mc_value=3.0,
            bin_width_magnitude=0.1,
            catalog_as_of=window_end,
            diagnostics_json={},
        )
        session.add(mc_record)
        session.commit()

        # Too few events for temporal ETAS to even attempt a fit -> a
        # not-converged, mu_per_day=None row, matching the not-estimable
        # discipline used throughout this project.
        etas_record = TemporalEtasService(
            session, policy=EtasPolicy(minimum_events=100)
        ).estimate_for_completeness_estimate(mc_record.id)
        assert etas_record.mu_per_day is None

        with pytest.raises(ValueError, match="did not converge"):
            IasEstimationService(session).estimate_for_temporal_etas_estimate(
                etas_record.id, evaluation_end_at=window_end
            )
