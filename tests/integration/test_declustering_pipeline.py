from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import (
    CompletenessEstimate,
    EventDeclusteringClassification,
    EventRevision,
    SourceEvent,
)
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.service import DeclusteringService, GutenbergRichterEstimationService


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/declustering-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"declustering-fixture",
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
async def test_full_chain_completeness_gr_declustering(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    """End-to-end: ingest a background+aftershock catalog, declare Mc
    directly (isolating this test from any single estimator's exact numeric
    output), fit b above it, then decluster above that Gutenberg-Richter
    estimate -- verifying the whole provenance chain
    (CompletenessEstimate -> GutenbergRichterEstimate ->
    SeismicityDeclusteringRun -> EventDeclusteringClassification) persists
    correctly and that declustering actually separates the two known
    populations on real ingested/queried data, not just on the pure
    function's own synthetic fixtures.
    """
    rng = np.random.default_rng(3)
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = window_start + timedelta(days=200)
    as_of = window_end

    events: list[NormalizedEvent] = []
    background_ids: set[str] = set()
    triggered_ids: set[str] = set()

    background_count = 200
    bg_days = rng.uniform(0, 200, size=background_count)
    bg_lat = rng.uniform(-34.0, -32.0, size=background_count)
    bg_lon = rng.uniform(-72.0, -70.0, size=background_count)
    for i in range(background_count):
        event_id = f"bg-{i}"
        event_time = window_start + timedelta(days=float(bg_days[i]))
        events.append(
            _event(
                source_event_id=event_id,
                event_time=event_time,
                available_at=event_time + timedelta(minutes=5),
                magnitude=3.5,
                latitude=float(bg_lat[i]),
                longitude=float(bg_lon[i]),
            )
        )
        background_ids.add(event_id)

    for cluster in range(2):
        main_day = rng.uniform(0, 180)
        main_lat, main_lon = rng.uniform(-34.0, -32.0), rng.uniform(-72.0, -70.0)
        main_id = f"main-{cluster}"
        main_time = window_start + timedelta(days=float(main_day))
        events.append(
            _event(
                source_event_id=main_id,
                event_time=main_time,
                available_at=main_time + timedelta(minutes=5),
                magnitude=5.0,
                latitude=float(main_lat),
                longitude=float(main_lon),
            )
        )
        background_ids.add(main_id)

        aftershock_count = 20
        after_dt = rng.exponential(1.0, size=aftershock_count)
        after_lat = main_lat + rng.normal(0, 0.02, size=aftershock_count)
        after_lon = main_lon + rng.normal(0, 0.02, size=aftershock_count)
        for i in range(aftershock_count):
            event_id = f"after-{cluster}-{i}"
            event_time = main_time + timedelta(days=float(after_dt[i]))
            events.append(
                _event(
                    source_event_id=event_id,
                    event_time=event_time,
                    available_at=event_time + timedelta(minutes=5),
                    magnitude=3.2,
                    latitude=float(after_lat[i]),
                    longitude=float(after_lon[i]),
                )
            )
            triggered_ids.add(event_id)

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
        assert gr_record.b_value is not None
        assert gr_record.events_at_or_above_mc == len(events)

        run = DeclusteringService(session).decluster_for_gutenberg_richter_estimate(gr_record.id)

        assert run.gutenberg_richter_estimate_id == gr_record.id
        assert run.b_value_used == gr_record.b_value
        assert run.event_count == len(events)
        assert run.log_eta_threshold is not None

        classification_rows = list(
            session.scalars(
                select(EventDeclusteringClassification).where(
                    EventDeclusteringClassification.declustering_run_id == run.id
                )
            )
        )
        assert len(classification_rows) == len(events)

        # Map classification rows (keyed by event_revision_id) back to
        # source_event_id so they can be checked against background_ids /
        # triggered_ids above.
        revision_rows = list(
            session.execute(
                select(EventRevision.id, SourceEvent.source_event_id).join(
                    SourceEvent, SourceEvent.id == EventRevision.source_event_id
                )
            )
        )
        source_id_by_revision_id = dict(revision_rows)

        by_source_id = {
            source_id_by_revision_id[row.event_revision_id]: row for row in classification_rows
        }

        background_correct = sum(1 for eid in background_ids if by_source_id[eid].is_background)
        triggered_correct = sum(
            1 for eid in triggered_ids if by_source_id[eid].is_background is False
        )
        assert background_correct / len(background_ids) > 0.8
        assert triggered_correct / len(triggered_ids) > 0.85
