from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.seismicity.catalog_selection import fetch_magnitude_catalog
from chile_oef.seismicity.completeness import CompletenessPolicy
from chile_oef.seismicity.service import CompletenessEstimationService


@dataclass
class FixtureEventAdapter:
    events: list[NormalizedEvent]
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/completeness-fixture",
            retrieved_at=self.events[0].received_at,
            content=b"completeness-fixture",
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
    magnitude_type: str = "ml",
) -> NormalizedEvent:
    return NormalizedEvent(
        source_id="usgs_comcat",
        source_event_id=source_event_id,
        event_time=event_time,
        received_at=available_at,
        available_at=available_at,
        latitude=-33.0,
        longitude=-71.5,
        depth_km=20.0,
        depth_uncertainty_km=5.0,
        magnitude=magnitude,
        magnitude_type=magnitude_type,
        source_payload={"id": source_event_id},
        parser_version="fixture-v1",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_availability_invariant_excludes_late_arriving_revision(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 2, 1, tzinfo=UTC)
    as_of = datetime(2026, 1, 20, tzinfo=UTC)

    on_time = _event(
        source_event_id="ontime-1",
        event_time=window_start + timedelta(days=5),
        available_at=window_start + timedelta(days=5, hours=1),
        magnitude=3.4,
    )
    # available_at is after as_of: the availability invariant in
    # docs/forecast-contract.md must exclude this revision even though its
    # event_time falls inside the window.
    late_arriving = _event(
        source_event_id="late-1",
        event_time=window_start + timedelta(days=6),
        available_at=as_of + timedelta(days=1),
        magnitude=5.9,
    )
    wrong_scale = _event(
        source_event_id="wrong-scale-1",
        event_time=window_start + timedelta(days=7),
        available_at=window_start + timedelta(days=7, hours=1),
        magnitude=4.1,
        magnitude_type="mw",
    )

    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter([on_time, late_arriving, wrong_scale])
        )

        selection = fetch_magnitude_catalog(
            session,
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert [o.magnitude for o in selection.observations] == [3.4]

        record = CompletenessEstimationService(
            session, policy=CompletenessPolicy()
        ).estimate_maximum_curvature(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert record.event_count == 1
        assert record.support_state == "not_estimable"
        assert record.mc_value is None
        assert record.role == "diagnostic"
        assert record.catalog_as_of == as_of


@pytest.mark.integration
@pytest.mark.asyncio
async def test_estimate_persists_supported_band_result(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    window_start = datetime(2026, 1, 1, tzinfo=UTC)
    window_end = datetime(2026, 2, 1, tzinfo=UTC)
    as_of = window_end

    events = [
        _event(
            source_event_id=f"bulk-{index}",
            event_time=window_start + timedelta(hours=index),
            available_at=window_start + timedelta(hours=index, minutes=5),
            magnitude=3.0,
        )
        for index in range(200)
    ]
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(events)
        )

        record = CompletenessEstimationService(session).estimate_maximum_curvature(
            as_of=as_of,
            start_time=window_start,
            end_time=window_end,
            magnitude_type="ml",
        )
        assert record.event_count == 200
        assert record.support_state == "supported"
        assert record.mc_value == pytest.approx(3.2)
        assert record.id is not None
