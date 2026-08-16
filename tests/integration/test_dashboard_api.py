import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.app.main import app
from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import CompletenessEstimate
from chile_oef.db.session import get_session
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
            source_url="https://example.test/dashboard-api-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"dashboard-api-fixture",
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
    place: str | None = None,
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
        place=place,
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
async def test_dashboard_endpoints_serve_a_real_fitted_forecast(
    postgis_engine: Engine, tmp_path: Path
) -> None:
    """End-to-end through the HTTP layer: ingest -> fit Mc/GR/spatiotemporal
    ETAS -> issue a forecast -> hit /v1/catalog/summary, /v1/forecasts,
    /v1/forecasts/{id}, and /v1/seismicity/model-summary and check they
    serve real, internally-consistent data (not placeholders).
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
            source_event_id=f"dash-{index}",
            event_time=window_start + timedelta(days=offset),
            available_at=window_start + timedelta(days=offset, minutes=5),
            magnitude=3.5,
            latitude=lat,
            longitude=lon,
            place="Fixture region, Chile" if index == 0 else None,
        )
        for index, (offset, lat, lon) in enumerate(events_data)
    ]

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(session, load_source_registry(Path("config/source-registry.yaml")))
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
                id="fixture_dashboard_grid_v1",
                resolution_degrees=Decimal("0.2"),
                min_latitude=Decimal(str(base_lat - region_deg / 2.0 - 0.5)),
                max_latitude=Decimal(str(base_lat + region_deg / 2.0 + 0.5)),
                min_longitude=Decimal(str(base_lon - region_deg / 2.0 - 0.5)),
                max_longitude=Decimal(str(base_lon + region_deg / 2.0 + 0.5)),
            )
        )

        specification = load_forecast_specification(Path("config/forecast-specification.yaml"))
        specification = type(specification)(
            version=specification.version,
            status=specification.status,
            grid_id=grid.id,
            horizons=specification.horizons,
            magnitude_bins=specification.magnitude_bins,
            reject_threshold_below_mc=specification.reject_threshold_below_mc,
            stale_data_action=specification.stale_data_action,
        )
        forecast_run = ForecastService(session, specification=specification).issue_forecast(
            spatiotemporal_etas_estimate_id=etas_record.id,
            gutenberg_richter_estimate_id=gr_record.id,
            issued_at=window_end,
            horizon_id="P1D",
        )

        def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                summary = await client.get("/v1/catalog/summary")
                assert summary.status_code == 200
                summary_body = summary.json()
                assert summary_body["total_events"] == len(events)
                assert summary_body["events_with_magnitude"] == len(events)
                assert any(
                    row["magnitude_type"] == "ml" for row in summary_body["magnitude_type_counts"]
                )
                assert "No predice terremotos" in summary_body["disclaimer"]

                model_summary = await client.get("/v1/seismicity/model-summary")
                assert model_summary.status_code == 200
                model_body = model_summary.json()
                assert model_body["spatiotemporal_etas_estimate_id"] == str(etas_record.id)
                assert model_body["gutenberg_richter_estimate_id"] == str(gr_record.id)
                assert model_body["mc_value"] == mc
                assert model_body["converged"] is True

                run_list = await client.get("/v1/forecasts")
                assert run_list.status_code == 200
                run_ids = [row["id"] for row in run_list.json()["data"]]
                assert str(forecast_run.id) in run_ids

                detail = await client.get(f"/v1/forecasts/{forecast_run.id}", params={"limit": 50})
                assert detail.status_code == 200
                detail_body = detail.json()
                assert detail_body["reference_magnitude"] == mc
                # Default bin selection must be at/above Mc, never the
                # (always empty) below-Mc bin -- the bug this test would
                # have caught.
                assert detail_body["selected_magnitude_lower"] >= mc
                assert len(detail_body["cells"]) > 0
                for cell in detail_body["cells"]:
                    assert cell["probability_at_least_one"] >= 0.0
                    assert cell["probability_at_least_one"] <= 1.0
                    assert cell["magnitude_lower"] == detail_body["selected_magnitude_lower"]

                explicit_bin = await client.get(
                    f"/v1/forecasts/{forecast_run.id}",
                    params={"magnitude_lower": 999.0},
                )
                assert explicit_bin.status_code == 422

                missing = await client.get("/v1/forecasts/00000000-0000-0000-0000-000000000000")
                assert missing.status_code == 404
        finally:
            app.dependency_overrides.clear()
