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
from chile_oef.db.models import CompletenessEstimate, SeismicCell, SeismicCellBackgroundRate
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.service import (
    BackgroundRateService,
    DeclusteringService,
    GutenbergRichterEstimationService,
)
from chile_oef.tectonics.grid import GridDefinition, GridService


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/background-rate-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"background-rate-fixture",
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


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_chain_completeness_gr_decluster_background_rate(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end through all four seismicity steps built so far:
    ingest -> declare Mc -> fit b -> decluster -> smooth the background
    subset over a real Phase 2 grid. Checks the full provenance chain
    persists (each row citing the specific upstream row it used) and that
    the background rate map is internally consistent (mass conservation
    against the known background event count, on a grid padded to fully
    contain the kernel bandwidths).
    """
    rng = np.random.default_rng(9)
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=200)
    as_of = window_end

    events: list[NormalizedEvent] = []
    background_count = 150
    bg_days = rng.uniform(0, 200, size=background_count)
    bg_lat = rng.uniform(-33.5, -32.5, size=background_count)
    bg_lon = rng.uniform(-71.5, -70.5, size=background_count)
    for i in range(background_count):
        event_time = window_start + timedelta(days=float(bg_days[i]))
        events.append(
            _event(
                source_event_id=f"bg-{i}",
                event_time=event_time,
                available_at=event_time + timedelta(minutes=5),
                magnitude=3.5,
                latitude=float(bg_lat[i]),
                longitude=float(bg_lon[i]),
            )
        )

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
            mc_value=3.0,
            bin_width_magnitude=0.1,
            catalog_as_of=as_of,
            diagnostics_json={},
        )
        session.add(mc_record)
        session.commit()

        gr_record = GutenbergRichterEstimationService(session).estimate_for_completeness_estimate(
            mc_record.id
        )
        declustering_run = DeclusteringService(session).decluster_for_gutenberg_richter_estimate(
            gr_record.id
        )
        assert declustering_run.background_event_count > 0

        # A grid well padded beyond the event scatter, so mass conservation
        # (see tests/unit/test_background_rate.py) is meaningful here too.
        grid = GridService(session).create(
            GridDefinition(
                id="fixture_background_rate_grid_v1",
                resolution_degrees=Decimal("0.1"),
                min_latitude=Decimal("-35.0"),
                max_latitude=Decimal("-31.0"),
                min_longitude=Decimal("-73.0"),
                max_longitude=Decimal("-69.0"),
            )
        )

        background_rate_run = BackgroundRateService(session).estimate_for_declustering_run(
            declustering_run.id, grid.id
        )

        assert background_rate_run.declustering_run_id == declustering_run.id
        assert background_rate_run.grid_id == grid.id
        assert background_rate_run.background_event_count == declustering_run.background_event_count

        cell_rates = list(
            session.scalars(
                select(SeismicCellBackgroundRate).where(
                    SeismicCellBackgroundRate.background_rate_run_id == background_rate_run.id
                )
            )
        )
        assert len(cell_rates) > 0

        cells = {
            cell.id: cell
            for cell in session.scalars(select(SeismicCell).where(SeismicCell.grid_id == grid.id))
        }
        total_mass = sum(rate.density_per_km2 * cells[rate.cell_id].area_km2 for rate in cell_rates)
        assert total_mass == pytest.approx(background_rate_run.background_event_count, rel=0.05)

        total_rate_per_year = sum(rate.rate_per_year for rate in cell_rates)
        expected_rate_per_year = background_rate_run.background_event_count / (
            background_rate_run.observation_duration_days / 365.25
        )
        assert total_rate_per_year == pytest.approx(expected_rate_per_year, rel=0.05)
