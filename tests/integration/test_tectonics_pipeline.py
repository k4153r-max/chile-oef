import hashlib
import io
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
import shapefile
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from chile_oef.app.main import app
from chile_oef.catalog.normalization import NormalizedEvent
from chile_oef.db.models import (
    EventRevision,
    EventTectonicClassification,
    FaultTrace,
    RawArtifact,
    SeismicCell,
    SlabNode,
    TectonicAsset,
    TectonicRelease,
)
from chile_oef.db.session import get_session
from chile_oef.ingestion.base import FetchedArtifact
from chile_oef.ingestion.raw_archive import RawArchive
from chile_oef.ingestion.registry import load_source_registry
from chile_oef.ingestion.service import IngestionService, sync_source_registry
from chile_oef.tectonics.assets import TectonicAssetService
from chile_oef.tectonics.faults import FaultService
from chile_oef.tectonics.grid import GridDefinition, GridService
from chile_oef.tectonics.registry import TectonicAssetSpec
from chile_oef.tectonics.service import EventClassificationService
from chile_oef.tectonics.slab2 import SlabAssetBundle, SlabService


@pytest.mark.integration
def test_verified_local_asset_import_is_audited(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    content = b"official-static-asset-fixture"
    local_path = tmp_path / "fixture.xyz"
    local_path.write_bytes(content)
    spec = TectonicAssetSpec(
        type="depth",
        filename="fixture.xyz",
        url="https://example.test/official/fixture.xyz",
        byte_length=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        release = TectonicRelease(
            source_id="slab2_south_america_2018",
            release_id="fixture_local_import_v1",
            title="Fixture local import",
            doi="https://doi.org/10.5066/F7PV6JNV",
            license_id="US-public-domain",
            status="building",
            metadata_json={},
        )
        session.add(release)
        session.commit()
        imported = TectonicAssetService(
            session,
            RawArchive(tmp_path / "raw-assets"),
        ).obtain_local(
            release,
            spec,
            local_path,
            parser_version="fixture-v1",
        )
        assert imported == content
        asset = session.scalar(select(TectonicAsset))
        assert asset is not None
        assert asset.metadata_json["acquisition_mode"] == "verified_local_import"
        raw = session.scalar(select(RawArtifact))
        assert raw is not None
        assert raw.source_url == spec.url
        assert raw.http_status is None


@dataclass
class FixtureEventAdapter:
    event: NormalizedEvent
    source_id = "usgs_comcat"
    parser_version = "fixture-v1"

    async def fetch(self) -> FetchedArtifact:
        return FetchedArtifact(
            source_id=self.source_id,
            source_url="https://example.test/tectonic-event",
            retrieved_at=self.event.received_at,
            content=b"tectonic-event-fixture",
            media_type="application/octet-stream",
            http_status=200,
        )

    def parse(self, artifact: FetchedArtifact) -> list[NormalizedEvent]:
        return [self.event]


def _xyz(values: list[float]) -> bytes:
    coordinates = [
        (287.95, -33.05),
        (288.00, -33.05),
        (287.95, -33.00),
        (288.00, -33.00),
    ]
    return "".join(
        f"{longitude},{latitude},{value}\n"
        for (longitude, latitude), value in zip(coordinates, values, strict=True)
    ).encode("ascii")


def _chaf_zip() -> bytes:
    shp = io.BytesIO()
    shx = io.BytesIO()
    dbf = io.BytesIO()
    with shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYLINE) as writer:
        writer.field("F_id", "C", size=12)
        writer.field("F_system", "C", size=40)
        writer.field("F_name", "C", size=40)
        writer.field("FT_name", "C", size=40)
        writer.field("type", "C", size=20)
        writer.field("activity", "C", size=20)
        writer.field("strike", "F", size=8, decimal=2)
        writer.field("dip", "F", size=8, decimal=2)
        writer.field("rake", "F", size=8, decimal=2)
        writer.field("length_km", "F", size=8, decimal=2)
        writer.line([[[-72.1, -33.1], [-71.9, -32.9]]])
        writer.record(
            "F001",
            "Central",
            "Fixture fault",
            "Trace 1",
            "reverse",
            "active",
            5,
            30,
            90,
            12,
        )
    archive_buffer = io.BytesIO()
    with zipfile.ZipFile(archive_buffer, "w") as archive:
        archive.writestr("fixture.shp", shp.getvalue())
        archive.writestr("fixture.shx", shx.getvalue())
        archive.writestr("fixture.dbf", dbf.getvalue())
    return archive_buffer.getvalue()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_versioned_tectonic_pipeline_and_api(
    postgis_engine: Engine,
    tmp_path: Path,
) -> None:
    with Session(postgis_engine, expire_on_commit=False) as session:
        sync_source_registry(
            session,
            load_source_registry(Path("config/source-registry.yaml")),
        )
        definition = GridDefinition(
            id="fixture_grid_v1",
            resolution_degrees=Decimal("0.1"),
            min_latitude=Decimal("-33.2"),
            max_latitude=Decimal("-33.0"),
            min_longitude=Decimal("-72.2"),
            max_longitude=Decimal("-72.0"),
        )
        GridService(session).create(definition)

        slab_release = TectonicRelease(
            source_id="slab2_south_america_2018",
            release_id="fixture_slab_v1",
            title="Fixture Slab2",
            doi="https://doi.org/10.5066/F7PV6JNV",
            license_id="US-public-domain",
            status="building",
            metadata_json={"resolution_degrees": 0.05},
        )
        fault_release = TectonicRelease(
            source_id="chaf_2020",
            release_id="fixture_chaf_v1",
            title="Fixture CHAF",
            doi="https://doi.org/10.1594/PANGAEA.922241",
            license_id="CC-BY-4.0",
            status="building",
            metadata_json={},
        )
        session.add_all([slab_release, fault_release])
        session.commit()
        SlabService(session).load_nodes(
            slab_release,
            SlabAssetBundle(
                depth=_xyz([-30.0] * 4),
                dip=_xyz([20.0] * 4),
                strike=_xyz([359.0, 1.0, 359.0, 1.0]),
                thickness=_xyz([60.0] * 4),
                uncertainty=_xyz([1.0] * 4),
            ),
        )
        FaultService(session).load_chaf(fault_release, _chaf_zip())

        observed_at = datetime(2026, 8, 16, 12, tzinfo=UTC)
        event = NormalizedEvent(
            source_id="usgs_comcat",
            source_event_id="fixture-tectonic-1",
            event_time=observed_at,
            received_at=observed_at,
            available_at=observed_at,
            latitude=-33.025,
            longitude=-72.025,
            depth_km=30.0,
            depth_uncertainty_km=1.0,
            magnitude=4.5,
            magnitude_type="mw",
            source_payload={"id": "fixture-tectonic-1"},
            parser_version="fixture-v1",
        )
        await IngestionService(session, RawArchive(tmp_path / "raw")).run(
            FixtureEventAdapter(event)
        )
        revision = session.scalar(
            select(EventRevision).where(EventRevision.revision_hash == event.revision_hash)
        )
        assert revision is not None

        service = EventClassificationService(
            session,
            slab_release=slab_release,
            fault_release=fault_release,
        )
        classification = service.classify_revision(revision)
        repeated = service.classify_revision(revision)
        assert repeated.id == classification.id
        assert classification.label == "interface"
        assert sum(classification.probabilities_json.values()) == pytest.approx(1.0)
        assert classification.horizontal_fault_distance_km is not None
        assert classification.calibration_status == "uncalibrated_rule_baseline"
        assert session.scalar(select(func.count()).select_from(EventTectonicClassification)) == 1
        assert session.scalar(select(func.count()).select_from(SlabNode)) == 4
        assert session.scalar(select(func.count()).select_from(FaultTrace)) == 1
        assert session.scalar(select(func.count()).select_from(SeismicCell)) == 4

        def override_session():
            yield session

        app.dependency_overrides[get_session] = override_session
        try:
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                grids = await client.get("/v1/grids")
                assert grids.status_code == 200
                assert grids.json()[0]["id"] == "fixture_grid_v1"

                cells = await client.get("/v1/cells", params={"grid_id": definition.id})
                assert cells.status_code == 200
                assert len(cells.json()) == 4

                sample = await client.get(
                    "/v1/tectonics/slab/sample",
                    params={
                        "release_id": str(slab_release.id),
                        "latitude": event.latitude,
                        "longitude": event.longitude,
                    },
                )
                assert sample.status_code == 200
                assert sample.json()["depth_km"] == pytest.approx(30.0)
                assert sample.json()["strike_degrees"] == pytest.approx(0.0, abs=1e-10)

                result = await client.get(f"/v1/tectonics/classifications/{revision.id}")
                assert result.status_code == 200
                assert result.json()[0]["calibration_status"] == ("uncalibrated_rule_baseline")

                wrong_release = await client.get(
                    "/v1/tectonics/slab/sample",
                    params={
                        "release_id": str(fault_release.id),
                        "latitude": event.latitude,
                        "longitude": event.longitude,
                    },
                )
                assert wrong_release.status_code == 404
        finally:
            app.dependency_overrides.clear()
