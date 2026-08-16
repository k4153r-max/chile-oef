import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from chile_oef import __version__
from chile_oef.app.api.schemas import (
    CellResponse,
    DatasetVersionResponse,
    EventDetailResponse,
    EventListResponse,
    EventResponse,
    EventRevisionResponse,
    GridResponse,
    HealthResponse,
    QualityFlagResponse,
    RawArtifactResponse,
    SlabSampleResponse,
    SourceStatusResponse,
    TectonicClassificationResponse,
    TectonicReleaseResponse,
)
from chile_oef.db.models import (
    CatalogSource,
    DatasetVersion,
    EventTectonicClassification,
    IngestionRun,
    RawArtifact,
    SeismicCell,
    SpatialGrid,
    TectonicRelease,
)
from chile_oef.db.repositories.events import get_event_revisions, list_events
from chile_oef.db.session import get_session
from chile_oef.tectonics.slab2 import SlabRepository

router = APIRouter()
SessionDependency = Annotated[Session, Depends(get_session)]


def _validate_catalog_query_times(
    *,
    as_of: datetime,
    start_time: datetime | None,
    end_time: datetime | None,
) -> None:
    for name, value in (
        ("as_of", as_of),
        ("start_time", start_time),
        ("end_time", end_time),
    ):
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise HTTPException(status_code=422, detail=f"{name} must include a timezone")
    if start_time is not None and end_time is not None and start_time >= end_time:
        raise HTTPException(status_code=422, detail="start_time must precede end_time")


@router.get("/health", response_model=HealthResponse)
def health(session: SessionDependency) -> HealthResponse:
    session.execute(text("SELECT 1"))
    return HealthResponse(status="ok", database="ok", version=__version__)


@router.get("/earthquakes", response_model=EventListResponse)
def earthquakes(
    session: SessionDependency,
    as_of: datetime | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    min_magnitude: float | None = None,
    min_latitude: float | None = Query(default=None, ge=-90, le=90),
    max_latitude: float | None = Query(default=None, ge=-90, le=90),
    min_longitude: float | None = Query(default=None, ge=-180, le=180),
    max_longitude: float | None = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> EventListResponse:
    effective_as_of = as_of or datetime.now(UTC)
    _validate_catalog_query_times(
        as_of=effective_as_of,
        start_time=start_time,
        end_time=end_time,
    )
    if min_latitude is not None and max_latitude is not None and min_latitude > max_latitude:
        raise HTTPException(status_code=422, detail="min_latitude exceeds max_latitude")
    if min_longitude is not None and max_longitude is not None and min_longitude > max_longitude:
        raise HTTPException(status_code=422, detail="min_longitude exceeds max_longitude")
    data = list_events(
        session,
        as_of=effective_as_of,
        start_time=start_time,
        end_time=end_time,
        min_magnitude=min_magnitude,
        min_latitude=min_latitude,
        max_latitude=max_latitude,
        min_longitude=min_longitude,
        max_longitude=max_longitude,
        limit=limit,
        offset=offset,
    )
    return EventListResponse(
        data=[EventResponse.model_validate(item) for item in data],
        as_of=effective_as_of,
        limit=limit,
        offset=offset,
    )


@router.get("/earthquakes/{canonical_id}", response_model=EventDetailResponse)
def earthquake_detail(
    canonical_id: uuid.UUID,
    session: SessionDependency,
    as_of: datetime | None = None,
) -> EventDetailResponse:
    revisions = get_event_revisions(session, canonical_id, as_of=as_of)
    if not revisions:
        raise HTTPException(status_code=404, detail="canonical event not found at as_of")
    items = []
    for revision, source_event, quality_logs in revisions:
        items.append(
            EventRevisionResponse(
                revision_id=revision.id,
                source_id=source_event.source_id,
                source_event_identifier=source_event.source_event_id,
                revision_hash=revision.revision_hash,
                event_time=revision.event_time,
                source_updated_at=revision.source_updated_at,
                received_at=revision.received_at,
                available_at=revision.available_at,
                latitude=revision.latitude,
                longitude=revision.longitude,
                depth_km=revision.depth_km,
                magnitude=revision.magnitude,
                magnitude_type=revision.magnitude_type,
                place=revision.place,
                parser_version=revision.parser_version,
                quality_flags=[
                    QualityFlagResponse(flag=log.flag, severity=log.severity, detail=log.detail)
                    for log in quality_logs
                ],
            )
        )
    return EventDetailResponse(canonical_id=canonical_id, revisions=items)


@router.get("/data-sources/status", response_model=list[SourceStatusResponse])
def source_status(session: SessionDependency) -> list[SourceStatusResponse]:
    last_run = (
        select(
            IngestionRun.source_id,
            func.max(IngestionRun.started_at).label("last_started_at"),
        )
        .group_by(IngestionRun.source_id)
        .subquery()
    )
    statement = (
        select(CatalogSource, IngestionRun)
        .outerjoin(last_run, last_run.c.source_id == CatalogSource.id)
        .outerjoin(
            IngestionRun,
            (IngestionRun.source_id == last_run.c.source_id)
            & (IngestionRun.started_at == last_run.c.last_started_at),
        )
        .order_by(CatalogSource.id)
    )
    return [
        SourceStatusResponse(
            source_id=source.id,
            enabled=source.enabled,
            last_run_started_at=run.started_at if run else None,
            last_run_finished_at=run.finished_at if run else None,
            last_run_status=run.status if run else None,
            records_seen=run.records_seen if run else None,
            revisions_inserted=run.revisions_inserted if run else None,
        )
        for source, run in session.execute(statement)
    ]


@router.get(
    "/provenance/artifacts/{source_id}/{sha256}",
    response_model=RawArtifactResponse,
)
def artifact_provenance(
    source_id: str,
    sha256: str,
    session: SessionDependency,
) -> RawArtifactResponse:
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise HTTPException(
            status_code=422,
            detail="sha256 must be 64 lowercase hex characters",
        )
    artifact = session.scalar(
        select(RawArtifact).where(
            RawArtifact.source_id == source_id,
            RawArtifact.sha256 == sha256,
        )
    )
    if artifact is None:
        raise HTTPException(status_code=404, detail="raw artifact not found")
    return RawArtifactResponse(
        source_id=artifact.source_id,
        retrieved_at=artifact.retrieved_at,
        source_url=artifact.source_url,
        storage_uri=artifact.storage_uri,
        sha256=artifact.sha256,
        byte_length=artifact.byte_length,
        media_type=artifact.media_type,
        http_status=artifact.http_status,
    )


@router.get(
    "/datasets/{dataset_id}/{version}",
    response_model=DatasetVersionResponse,
)
def dataset_version(
    dataset_id: str,
    version: str,
    session: SessionDependency,
) -> DatasetVersionResponse:
    dataset = session.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version == version,
        )
    )
    if dataset is None:
        raise HTTPException(status_code=404, detail="dataset version not found")
    return DatasetVersionResponse(
        dataset_id=dataset.dataset_id,
        version=dataset.version,
        as_of=dataset.as_of,
        created_at=dataset.created_at,
        manifest_sha256=dataset.manifest_sha256,
        git_commit=dataset.git_commit,
        manifest=dataset.manifest_json,
    )


@router.get("/grids", response_model=list[GridResponse])
def grids(session: SessionDependency) -> list[GridResponse]:
    return [
        GridResponse(
            id=grid.id,
            resolution_degrees=grid.resolution_degrees,
            min_latitude=grid.min_latitude,
            max_latitude=grid.max_latitude,
            min_longitude=grid.min_longitude,
            max_longitude=grid.max_longitude,
            status=grid.status,
            definition_sha256=grid.definition_sha256,
            metadata=grid.metadata_json,
        )
        for grid in session.scalars(select(SpatialGrid).order_by(SpatialGrid.id))
    ]


@router.get("/cells", response_model=list[CellResponse])
def cells(
    session: SessionDependency,
    grid_id: str,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
) -> list[CellResponse]:
    statement = (
        select(SeismicCell)
        .where(SeismicCell.grid_id == grid_id)
        .order_by(SeismicCell.row_index, SeismicCell.column_index)
        .limit(limit)
        .offset(offset)
    )
    return [
        CellResponse(
            id=cell.id,
            grid_id=cell.grid_id,
            row_index=cell.row_index,
            column_index=cell.column_index,
            center_latitude=cell.center_latitude,
            center_longitude=cell.center_longitude,
            area_km2=cell.area_km2,
        )
        for cell in session.scalars(statement)
    ]


@router.get("/tectonics/releases", response_model=list[TectonicReleaseResponse])
def tectonic_releases(session: SessionDependency) -> list[TectonicReleaseResponse]:
    return [
        TectonicReleaseResponse(
            id=release.id,
            source_id=release.source_id,
            release_id=release.release_id,
            title=release.title,
            doi=release.doi,
            license_id=release.license_id,
            status=release.status,
            metadata=release.metadata_json,
        )
        for release in session.scalars(select(TectonicRelease).order_by(TectonicRelease.source_id))
    ]


@router.get("/tectonics/slab/sample", response_model=SlabSampleResponse)
def slab_sample(
    session: SessionDependency,
    release_id: uuid.UUID,
    latitude: float = Query(ge=-90, le=90),
    longitude: float = Query(ge=-180, le=180),
) -> SlabSampleResponse:
    release = session.get(TectonicRelease, release_id)
    if (
        release is None
        or release.status != "ready"
        or release.source_id != "slab2_south_america_2018"
    ):
        raise HTTPException(status_code=404, detail="ready slab release not found")
    resolution = float(release.metadata_json.get("resolution_degrees", 0.05))
    sample = SlabRepository(session, release.id, resolution=resolution).sample(
        latitude=latitude,
        longitude=longitude,
    )
    if sample is None:
        raise HTTPException(status_code=404, detail="point outside finite slab coverage")
    return SlabSampleResponse(
        latitude=latitude,
        longitude=longitude,
        depth_km=sample.depth_km,
        dip_degrees=sample.dip_degrees,
        strike_degrees=sample.strike_degrees,
        thickness_km=sample.thickness_km,
        uncertainty_km=sample.uncertainty_km,
        interpolation=sample.interpolation,
        contributing_nodes=sample.contributing_nodes,
    )


@router.get(
    "/tectonics/classifications/{revision_id}",
    response_model=list[TectonicClassificationResponse],
)
def tectonic_classifications(
    revision_id: uuid.UUID,
    session: SessionDependency,
) -> list[TectonicClassificationResponse]:
    rows = list(
        session.scalars(
            select(EventTectonicClassification)
            .where(EventTectonicClassification.event_revision_id == revision_id)
            .order_by(EventTectonicClassification.created_at.desc())
        )
    )
    return [
        TectonicClassificationResponse(
            id=row.id,
            event_revision_id=row.event_revision_id,
            slab_release_id=row.slab_release_id,
            fault_release_id=row.fault_release_id,
            method_version=row.method_version,
            calibration_status=row.calibration_status,
            label=row.label,
            max_probability=row.max_probability,
            slab_depth_km=row.slab_depth_km,
            signed_vertical_residual_km=row.signed_vertical_residual_km,
            signed_normal_distance_km=row.signed_normal_distance_km,
            horizontal_fault_distance_km=row.horizontal_fault_distance_km,
            probabilities=row.probabilities_json,
            diagnostics=row.diagnostics_json,
            created_at=row.created_at,
        )
        for row in rows
    ]
