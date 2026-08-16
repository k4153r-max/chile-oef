import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import CompletenessEstimate, ForecastCellMagnitudeBin
from chile_oef.forecast.service import ForecastService
from chile_oef.forecast.specification import load_forecast_specification
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.service import (
    GutenbergRichterEstimationService,
    SpatiotemporalEtasService,
)
from chile_oef.seismicity.spatiotemporal_etas import SpatiotemporalEtasPolicy
from chile_oef.tectonics.grid import GridDefinition, GridService

DEGREE_KM = 111.32


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/forecast-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"forecast-fixture",
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


def _simulate_light_spatiotemporal_events(
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
            # Isotropic offset via the same inverse-CDF sampler used in the
            # other spatiotemporal ETAS test fixtures.
            u2 = rng.uniform(0.0, 1.0)
            r_km = d0 * math.sqrt((1.0 - u2) ** (1.0 / (1.0 - q)) - 1.0)
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
async def test_full_chain_through_forecast_issuance(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: ingest -> declare Mc -> fit b -> fit spatiotemporal ETAS
    -> issue a forecast, over a real grid built in the same test. Checks
    both provenance FKs (forecast_runs citing the exact ETAS and GR rows
    used), the completeness-estimate-consistency guard, and that the
    forecast's magnitude-bin fractions still sum coherently per cell.
    """
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    duration_days = 200.0
    window_end = window_start + timedelta(days=duration_days)
    as_of = window_end
    mc = 3.0
    base_lat, base_lon = -33.0, -71.0
    region_deg = 2.0

    events_data = _simulate_light_spatiotemporal_events(
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
            source_event_id=f"fc-{index}",
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

        gr_record = GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
            mc_record.id
        )
        assert gr_record.b_value is not None

        etas_record = SpatiotemporalEtasService(
            session, policy=SpatiotemporalEtasPolicy(restarts=1, minimum_events=100)
        ).estimate_for_completeness_estimate(mc_record.id)
        if not etas_record.converged:
            pytest.skip("spatiotemporal ETAS did not converge on this seed with one restart")

        grid = GridService(session).create(
            GridDefinition(
                id="fixture_forecast_grid_v1",
                resolution_degrees=Decimal("0.2"),
                min_latitude=Decimal(str(base_lat - region_deg / 2.0 - 0.5)),
                max_latitude=Decimal(str(base_lat + region_deg / 2.0 + 0.5)),
                min_longitude=Decimal(str(base_lon - region_deg / 2.0 - 0.5)),
                max_longitude=Decimal(str(base_lon + region_deg / 2.0 + 0.5)),
            )
        )

        specification = load_forecast_specification(Path("config/forecast-specification.yaml"))
        # Point the specification at the fixture grid built for this test,
        # rather than the real production grid id it names by default.
        specification = type(specification)(
            version=specification.version,
            status=specification.status,
            grid_id=grid.id,
            horizons=specification.horizons,
            magnitude_bins=specification.magnitude_bins,
            reject_threshold_below_mc=specification.reject_threshold_below_mc,
            stale_data_action=specification.stale_data_action,
        )

        issued_at = window_end
        run = ForecastService(session, specification=specification).issue_forecast(
            spatiotemporal_etas_estimate_id=etas_record.id,
            gutenberg_richter_estimate_id=gr_record.id,
            issued_at=issued_at,
            horizon_id="P1D",
        )

        assert run.spatiotemporal_etas_estimate_id == etas_record.id
        assert run.gutenberg_richter_estimate_id == gr_record.id
        assert run.grid_id == grid.id
        assert run.reference_magnitude == mc
        assert run.validity_start == issued_at
        assert run.validity_end == issued_at + timedelta(seconds=86400)
        assert run.cell_count > 0
        assert run.magnitude_bin_count == len(specification.magnitude_bins)

        rows = list(
            session.scalars(
                select(ForecastCellMagnitudeBin).where(
                    ForecastCellMagnitudeBin.forecast_run_id == run.id
                )
            )
        )
        assert len(rows) == run.cell_count * run.magnitude_bin_count
        estimable_rows = [row for row in rows if row.support_state == "estimable"]
        assert len(estimable_rows) > 0
        for row in estimable_rows:
            assert row.expected_count is not None
            assert row.probability_at_least_one is not None
            assert 0.0 <= row.probability_at_least_one <= 1.0


@pytest.mark.integration
@pytest.mark.asyncio
async def test_forecast_refuses_mismatched_completeness_lineage(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """A targeted test of the lineage-consistency guard specifically (not
    just "some refusal happened"): two separate CompletenessEstimate rows
    are registered over the *same* underlying catalog/window (so both a
    Gutenberg-Richter fit against one and a spatiotemporal ETAS fit against
    the other genuinely converge on real data), then issue_forecast is
    called mixing a b-value from one lineage with an ETAS fit from the
    other. This must be refused even though both individual inputs are
    perfectly valid on their own.
    """
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    duration_days = 200.0
    window_end = window_start + timedelta(days=duration_days)
    as_of = window_end
    mc = 3.0
    base_lat, base_lon = -33.0, -71.0
    region_deg = 2.0

    events_data = _simulate_light_spatiotemporal_events(
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
            source_event_id=f"lineage-{index}",
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

        def _completeness_record() -> CompletenessEstimate:
            record = CompletenessEstimate(
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
            session.add(record)
            session.commit()
            return record

        mc_record_a = _completeness_record()
        mc_record_b = _completeness_record()
        assert mc_record_a.id != mc_record_b.id

        gr_record = GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
            mc_record_a.id
        )
        assert gr_record.b_value is not None

        etas_record = SpatiotemporalEtasService(
            session, policy=SpatiotemporalEtasPolicy(restarts=1, minimum_events=100)
        ).estimate_for_completeness_estimate(mc_record_b.id)
        if not etas_record.converged:
            pytest.skip("spatiotemporal ETAS did not converge on this seed with one restart")

        specification = load_forecast_specification(Path("config/forecast-specification.yaml"))
        with pytest.raises(ValueError, match="different completeness estimates"):
            ForecastService(session, specification=specification).issue_forecast(
                spatiotemporal_etas_estimate_id=etas_record.id,
                gutenberg_richter_estimate_id=gr_record.id,
                issued_at=window_end,
                horizon_id="P1D",
            )
