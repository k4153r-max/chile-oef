import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.app.main import app
from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.datasets.service import DatasetVersionService
from chile_oef.db.models import (
    CanonicalEvent,
    CanonicalEventMembership,
    DatasetArtifact,
    DatasetEventRevision,
    EventRevision,
    IngestionArtifact,
    IngestionRun,
    RawArtifact,
    SourceEvent,
)
from chile_oef.db.repositories.events import list_events
from chile_oef.db.session import get_session
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.ingestion.sources.usgs_geojson import UsgsGeoJsonAdapter


@dataclass
class FixtureUsgsAdapter(UsgsGeoJsonAdapter):
    artifact: FetchedArtifact

    def __post_init__(self) -> None:
        UsgsGeoJsonAdapter.__init__(self)

    async def fetch(self) -> FetchedArtifact:
        return self.artifact


@dataclass
class FixtureNormalizedAdapter:
    source_id: str
    event: NormalizedEvent

    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url=f"https://example.test/{self.source_id}/{self.event.source_event_id}",
            retrieved_at=self.event.received_at,
            content=f"{self.source_id}:{self.event.source_event_id}".encode(),
            media_type="application/octet-stream",
            http_status=200,
        )

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        return [self.event]


class FailingAdapter:
    source_id = "usgs_comcat"
    parser_version = "fixture-failure-v1"
    url = "https://example.test/unavailable"

    async def fetch(self) -> FetchedArtifact:
        raise RuntimeError("fixture source unavailable")

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        raise AssertionError("parse must not run after a failed fetch")


def _artifact(content: bytes, retrieved_at: datetime) -> FetchedArtifact:
    return FetchedArtifact(
        source_id="usgs_comcat",
        source_url="https://example.test/usgs.geojson",
        retrieved_at=retrieved_at,
        content=content,
        media_type="application/geo+json",
        http_status=200,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bitemporal_ingestion_dataset_and_api(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    first_available = datetime(2026, 8, 16, 12, tzinfo=UTC)
    revised_available = first_available + timedelta(hours=1)
    payload = Path("tests/fixtures/usgs/all_hour.geojson").read_bytes()
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        service = IngestionService(session, RawArchive(tmp_path / "raw"))
        first = await service.run(FixtureUsgsAdapter(_artifact(payload, first_available)))
        repeated = await service.run(
            FixtureUsgsAdapter(_artifact(payload, first_available + timedelta(minutes=5)))
        )

        revised_document = json.loads(payload)
        revised_document["features"][0]["properties"]["mag"] = 4.4
        revised_payload = json.dumps(revised_document).encode()
        revised = await service.run(
            FixtureUsgsAdapter(_artifact(revised_payload, revised_available))
        )

        assert (first.records_seen, first.revisions_inserted, first.artifacts_inserted) == (
            2,
            2,
            1,
        )
        assert (
            repeated.records_seen,
            repeated.revisions_inserted,
            repeated.artifacts_inserted,
        ) == (2, 0, 0)
        assert (revised.records_seen, revised.revisions_inserted) == (2, 1)
        assert session.scalar(select(func.count()).select_from(SourceEvent)) == 2
        assert session.scalar(select(func.count()).select_from(EventRevision)) == 3
        assert session.scalar(select(func.count()).select_from(RawArtifact)) == 2
        assert session.scalar(select(func.count()).select_from(IngestionArtifact)) == 3
        assert session.scalar(select(func.count()).select_from(CanonicalEvent)) == 2
        assert session.scalar(text("SELECT count(*) FROM geometry_columns")) >= 1

        before_revision = list_events(
            session,
            as_of=first_available + timedelta(minutes=30),
        )
        after_revision = list_events(
            session,
            as_of=revised_available + timedelta(minutes=1),
        )
        assert max(item.magnitude or 0 for item in before_revision) == 4.2
        assert max(item.magnitude or 0 for item in after_revision) == 4.4

        dataset = DatasetVersionService(session).create(
            dataset_id="catalog",
            version="pre-revision",
            as_of=first_available + timedelta(minutes=30),
            created_at=revised_available + timedelta(hours=1),
            git_commit="a" * 40,
        )
        assert dataset.manifest_json["selection"]["time_axis"] == "available_at"
        assert len(dataset.manifest_json["event_revisions"]) == 2
        assert session.scalar(select(func.count()).select_from(DatasetArtifact)) == 1
        assert session.scalar(select(func.count()).select_from(DatasetEventRevision)) == 2

        def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                health = await client.get("/v1/health")
                assert health.status_code == 200

                naive_time = await client.get(
                    "/v1/earthquakes",
                    params={"as_of": "2026-08-16T12:00:00"},
                )
                assert naive_time.status_code == 422

                reversed_bounds = await client.get(
                    "/v1/earthquakes",
                    params={"min_latitude": -20, "max_latitude": -40},
                )
                assert reversed_bounds.status_code == 422

                response = await client.get(
                    "/v1/earthquakes",
                    params={"as_of": (revised_available + timedelta(minutes=1)).isoformat()},
                )
                assert response.status_code == 200
                assert len(response.json()["data"]) == 2
                assert "No predice terremotos" in response.json()["disclaimer"]

                dataset_response = await client.get("/v1/datasets/catalog/pre-revision")
                assert dataset_response.status_code == 200
                assert dataset_response.json()["manifest_sha256"] == dataset.manifest_sha256

                artifact = session.scalars(
                    select(RawArtifact).order_by(RawArtifact.retrieved_at)
                ).first()
                provenance = await client.get(
                    f"/v1/provenance/artifacts/{artifact.source_id}/{artifact.sha256}"
                )
                assert provenance.status_code == 200
                assert provenance.json()["byte_length"] == len(payload)
        finally:
            app.dependency_overrides.clear()


def _normalized(
    *,
    source_id: str,
    source_event_id: str,
    available_at: datetime,
    latitude: float,
    longitude: float,
) -> NormalizedEvent:
    return NormalizedEvent(
        source_id=source_id,
        source_event_id=source_event_id,
        event_time=datetime(2026, 8, 17, 10, tzinfo=UTC),
        received_at=available_at,
        available_at=available_at,
        latitude=latitude,
        longitude=longitude,
        depth_km=30.0,
        magnitude=5.0,
        magnitude_type="mw",
        source_payload={"source_event_id": source_event_id},
        parser_version="fixture-v1",
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cross_source_deduplication_preserves_observations(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    available_at = datetime(2026, 8, 17, 10, 1, tzinfo=UTC)
    usgs_event = _normalized(
        source_id="usgs_comcat",
        source_event_id="us-dedupe-1",
        available_at=available_at,
        latitude=-33.0,
        longitude=-72.0,
    )
    csn_event = _normalized(
        source_id="csn_daily",
        source_event_id="csn-dedupe-1",
        available_at=available_at + timedelta(minutes=1),
        latitude=-33.0,
        longitude=-72.0,
    )
    distinct_usgs_event = _normalized(
        source_id="usgs_comcat",
        source_event_id="us-dedupe-2",
        available_at=available_at + timedelta(minutes=2),
        latitude=-33.0,
        longitude=-72.0,
    )
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        canonical_before = session.scalar(select(func.count()).select_from(CanonicalEvent))
        service = IngestionService(session, RawArchive(tmp_path / "dedupe-raw"))
        await service.run(FixtureNormalizedAdapter("usgs_comcat", usgs_event))
        await service.run(FixtureNormalizedAdapter("csn_daily", csn_event))
        await service.run(FixtureNormalizedAdapter("usgs_comcat", distinct_usgs_event))

        canonical_after = session.scalar(select(func.count()).select_from(CanonicalEvent))
        memberships = session.scalars(
            select(CanonicalEventMembership).where(
                CanonicalEventMembership.source_event_id.in_(
                    select(SourceEvent.id).where(
                        SourceEvent.source_event_id.in_(("us-dedupe-1", "csn-dedupe-1"))
                    )
                )
            )
        ).all()
        assert canonical_after == canonical_before + 2
        assert len({membership.canonical_event_id for membership in memberships}) == 1
        assert len(memberships) == 2
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceEvent)
                .where(
                    SourceEvent.source_event_id.in_(("us-dedupe-1", "csn-dedupe-1", "us-dedupe-2"))
                )
            )
            == 3
        )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_failed_fetch_is_auditable(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        service = IngestionService(session, RawArchive(tmp_path / "failure-raw"))

        with pytest.raises(RuntimeError, match="source unavailable"):
            await service.run(FailingAdapter())

        run = session.scalar(select(IngestionRun))
        assert run is not None
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.request_url == FailingAdapter.url
        assert run.error_message == "fixture source unavailable"
