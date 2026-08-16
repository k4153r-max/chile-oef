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
from chile_oef.seismicity.service import SpatiotemporalEtasService
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasPolicy

DEGREE_KM = 111.32


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/spatiotemporal-etas-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"spatiotemporal-etas-fixture",
            media_type="application/octet-stream",
            http_status=200,
        )

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        return self.events


def _event(
    *,
    source_event_id: str,
    event_time: datetime,
    available_at: datetime,
    magnitude: float,
    latitude: float,
    longitude: float,
) -> NormalizedEvent:
    return NormalizedEvent(
        source_id="usgs_comcat",
        source_event_id=source_event_id,
        event_time=event_time,
        received_at=available_at,
        available_at=available_at,
        latitude=latitude,
        longitude=longitude,
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


def _sample_radius_km(rng: np.random.Generator, d_km: float, q: float) -> float:
    u = rng.uniform(0.0, 1.0)
    return d_km * math.sqrt((1.0 - u) ** (1.0 / (1.0 - q)) - 1.0)


def _simulate_light_spatiotemporal_etas(
    *,
    mu: float,
    k0: float,
    c: float,
    p: float,
    d0: float,
    q: float,
    duration_days: float,
    base_lat: float,
    base_lon: float,
    region_deg: float,
    seed: int,
) -> list[tuple[float, float, float]]:
    """Lighter version of the branching-process simulation in
    tests/unit/test_spatiotemporal_etas.py (constant magnitude, alpha=0,
    gamma=0): this test only needs plumbing/persistence exercised on real
    ingested data -- numeric recovery precision is already covered there.
    """
    rng = np.random.default_rng(seed)
    background_count = rng.poisson(mu * duration_days)
    events: list[tuple[float, float, float]] = []
    queue: list[tuple[float, float, float]] = []
    for _ in range(background_count):
        t0 = float(rng.uniform(0.0, duration_days))
        lat0 = base_lat + rng.uniform(-region_deg / 2.0, region_deg / 2.0)
        lon0 = base_lon + rng.uniform(-region_deg / 2.0, region_deg / 2.0)
        events.append((t0, lat0, lon0))
        queue.append((t0, lat0, lon0))
    while queue:
        if len(events) > 5000:
            raise RuntimeError("synthetic catalog exploded")
        parent_time, parent_lat, parent_lon = queue.pop()
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
            r_km = _sample_radius_km(rng, d0, q)
            theta = rng.uniform(0.0, 2.0 * math.pi)
            child_lat = parent_lat + (r_km * math.cos(theta)) / DEGREE_KM
            child_lon = parent_lon + (r_km * math.sin(theta)) / (
                DEGREE_KM * math.cos(math.radians(parent_lat))
            )
            events.append((child_time, child_lat, child_lon))
            queue.append((child_time, child_lat, child_lon))
    events.sort(key=lambda event: event[0])
    return events


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spatiotemporal_etas_persists_through_the_service(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: ingest a real catalog, declare Mc (with a bounding box,
    required for spatiotemporal ETAS), fit above it, and confirm the
    provenance FK, region area, and persisted fields are correct. Numeric
    parameter-recovery precision is covered by
    tests/unit/test_spatiotemporal_etas.py; this only exercises the real
    ingest -> select -> fit -> persist path, including the region-area
    computation from the completeness estimate's bounding box.
    """
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    duration_days = 200.0
    window_end = window_start + timedelta(days=duration_days)
    as_of = window_end
    mc = 3.0
    base_lat, base_lon = -33.0, -71.0
    region_deg = 2.0

    events_data = _simulate_light_spatiotemporal_etas(
        mu=1.0,
        k0=0.05,
        c=0.1,
        p=1.2,
        d0=5.0,
        q=1.8,
        duration_days=duration_days,
        base_lat=base_lat,
        base_lon=base_lon,
        region_deg=region_deg,
        seed=5,
    )
    assert len(events_data) >= 100, "synthetic catalog too small for this seed"

    events = [
        _event(
            source_event_id=f"st-etas-{index}",
            event_time=window_start + timedelta(days=offset),
            available_at=window_start + timedelta(days=offset, minutes=5),
            magnitude=3.5,
            latitude=lat,
            longitude=lon,
        )
        for index, (offset, lat, lon) in enumerate(events_data)
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
            min_latitude=base_lat - region_deg / 2.0,
            max_latitude=base_lat + region_deg / 2.0,
            min_longitude=base_lon - region_deg / 2.0,
            max_longitude=base_lon + region_deg / 2.0,
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

        record = SpatiotemporalEtasService(
            session, policy=SpatiotemporalEtasPolicy(restarts=1, minimum_events=100)
        ).estimate_for_completeness_estimate(mc_record.id)

        assert record.completeness_estimate_id == mc_record.id
        assert record.initial_guess_source_id is None
        # Some offspring get pushed outside the bounding box by the spatial
        # kernel's heavy tail (q close to 1 is heavy-tailed by design), so
        # the fitted event_count is correctly <= the ingested count once
        # the region filter is applied -- not necessarily equal.
        assert 100 <= record.event_count <= len(events)
        assert record.reference_magnitude == mc
        assert record.observation_duration_days == pytest.approx(duration_days)
        expected_area = (region_deg * DEGREE_KM) * (
            region_deg * DEGREE_KM * math.cos(math.radians(abs(base_lat)))
        )
        assert record.region_area_km2 == pytest.approx(expected_area, rel=0.01)
        if record.converged:
            assert record.mu_per_day is not None
            assert record.d0_km is not None
            assert record.q_exponent is not None
        else:
            assert record.mu_per_day is None
        assert record.id is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_spatiotemporal_etas_refuses_a_completeness_estimate_without_a_bounding_box(
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

        with pytest.raises(ValueError, match="no bounding box"):
            SpatiotemporalEtasService(session).estimate_for_completeness_estimate(mc_record.id)
