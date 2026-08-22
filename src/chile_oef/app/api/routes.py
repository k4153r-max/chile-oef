import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from chile_oef import __version__
from chile_oef.app.api.schemas import (
    CatalogSummaryResponse,
    CellResponse,
    DatasetVersionResponse,
    EventDetailResponse,
    EventListResponse,
    EventResponse,
    EventRevisionResponse,
    ForecastCellResponse,
    ForecastMagnitudeBinResponse,
    ForecastOperationalStatusResponse,
    ForecastPlacesResponse,
    ForecastRunDetailResponse,
    ForecastRunListResponse,
    ForecastRunSummaryResponse,
    GridResponse,
    HealthResponse,
    MagnitudeTypeCountResponse,
    NotableEventResponse,
    PlaceForecastResponse,
    QualityFlagResponse,
    RawArtifactResponse,
    SeismicityModelSummaryResponse,
    SlabSampleResponse,
    SourceStatusResponse,
    TectonicClassificationResponse,
    TectonicReleaseResponse,
)
from chile_oef.db.models import (
    CatalogSource,
    CompletenessEstimate,
    DatasetVersion,
    EventRevision,
    EventTectonicClassification,
    ForecastCellMagnitudeBin,
    ForecastRun,
    GutenbergRichterEstimate,
    IngestionRun,
    RawArtifact,
    SeismicCell,
    SpatialGrid,
    SpatiotemporalEtasEstimate,
    TectonicRelease,
)
from chile_oef.db.repositories.events import get_event_revisions, list_events
from chile_oef.db.session import get_session
from chile_oef.forecast.operations import assess_forecast_freshness
from chile_oef.forecast.places import (
    DEFAULT_RADIUS_KM,
    PLACES,
    bounding_box,
    estimate_place,
)
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


@router.get("/catalog/summary", response_model=CatalogSummaryResponse)
def catalog_summary(session: SessionDependency) -> CatalogSummaryResponse:
    """Aggregate stats over every ingested event revision -- not
    deduplicated across canonical events (a single bulk backfill from one
    source rarely produces multiple revisions per event), intended as a
    real-data dashboard summary, not a precise scientific catalog count.
    """
    total_events = session.scalar(select(func.count()).select_from(EventRevision)) or 0
    events_with_magnitude = (
        session.scalar(
            select(func.count())
            .select_from(EventRevision)
            .where(EventRevision.magnitude.isnot(None))
        )
        or 0
    )
    earliest_event_time = session.scalar(select(func.min(EventRevision.event_time)))
    latest_event_time = session.scalar(select(func.max(EventRevision.event_time)))
    type_counts = session.execute(
        select(EventRevision.magnitude_type, func.count())
        .group_by(EventRevision.magnitude_type)
        .order_by(func.count().desc())
    ).all()
    top_rows = session.execute(
        select(
            EventRevision.event_time,
            EventRevision.magnitude,
            EventRevision.magnitude_type,
            EventRevision.place,
            EventRevision.latitude,
            EventRevision.longitude,
        )
        .where(EventRevision.magnitude.isnot(None))
        .order_by(EventRevision.magnitude.desc())
        .limit(10)
    ).all()
    return CatalogSummaryResponse(
        total_events=total_events,
        events_with_magnitude=events_with_magnitude,
        earliest_event_time=earliest_event_time,
        latest_event_time=latest_event_time,
        magnitude_type_counts=[
            MagnitudeTypeCountResponse(magnitude_type=magnitude_type, count=count)
            for magnitude_type, count in type_counts
        ],
        top_magnitude_events=[
            NotableEventResponse(
                event_time=event_time,
                magnitude=magnitude,
                magnitude_type=magnitude_type,
                place=place,
                latitude=latitude,
                longitude=longitude,
            )
            for event_time, magnitude, magnitude_type, place, latitude, longitude in top_rows
        ],
    )


@router.get("/forecasts", response_model=ForecastRunListResponse)
def forecast_runs(
    session: SessionDependency,
    limit: int = Query(default=20, ge=1, le=100),
) -> ForecastRunListResponse:
    rows = session.scalars(select(ForecastRun).order_by(ForecastRun.issued_at.desc()).limit(limit))
    return ForecastRunListResponse(
        data=[
            ForecastRunSummaryResponse(
                id=run.id,
                issued_at=run.issued_at,
                validity_start=run.validity_start,
                validity_end=run.validity_end,
                horizon_id=run.horizon_id,
                cell_count=run.cell_count,
                magnitude_bin_count=run.magnitude_bin_count,
                reference_magnitude=run.reference_magnitude,
                b_value_used=run.b_value_used,
                calibration_status=run.calibration_status,
                method_version=run.method_version,
                background_rate_run_id=run.background_rate_run_id,
                background_spatial_model=run.diagnostics_json.get(
                    "background_spatial_model", "homogeneous_area_weighted"
                ),
                predictive_catalog_simulations=(
                    run.diagnostics_json.get("predictive_catalog_simulation", {}).get(
                        "simulation_count"
                    )
                ),
            )
            for run in rows
        ]
    )


@router.get("/forecasts/status", response_model=ForecastOperationalStatusResponse)
def forecast_operational_status(session: SessionDependency) -> ForecastOperationalStatusResponse:
    as_of = datetime.now(UTC)
    run = session.scalar(select(ForecastRun).order_by(ForecastRun.issued_at.desc()).limit(1))
    freshness = assess_forecast_freshness(run, as_of=as_of)
    stability = run.diagnostics_json.get("etas_stability", {}) if run is not None else {}
    return ForecastOperationalStatusResponse(
        state=freshness.state,
        as_of=as_of,
        latest_forecast_run_id=run.id if run is not None else None,
        latest_issued_at=run.issued_at if run is not None else None,
        latest_validity_end=run.validity_end if run is not None else None,
        age_seconds=freshness.age_seconds,
        valid_now=freshness.valid_now,
        expected_issue_interval_seconds=freshness.expected_issue_interval_seconds,
        background_spatial_model=(
            run.diagnostics_json.get("background_spatial_model") if run is not None else None
        ),
        etas_stability_state=stability.get("state"),
    )


@router.get("/forecasts/{forecast_run_id}", response_model=ForecastRunDetailResponse)
def forecast_run_detail(
    forecast_run_id: uuid.UUID,
    session: SessionDependency,
    magnitude_lower: float | None = None,
    limit: int = Query(default=3000, ge=1, le=10_000),
) -> ForecastRunDetailResponse:
    """Cell detail for one magnitude bin at a time (a real forecast run
    over the production grid has 90,000 cells x 5 bins = 450,000 rows,
    far more than a browser map should ever fetch at once). Defaults to
    the lowest registered magnitude bin -- the most event-rich, most
    visually informative one -- and returns only `support_state
    == "estimable"` cells ranked by expected count, since the overwhelming
    majority of cells carry only background-level, visually meaningless
    rates.
    """
    run = session.get(ForecastRun, forecast_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="forecast run not found")
    bin_rows = session.execute(
        select(ForecastCellMagnitudeBin.magnitude_lower, ForecastCellMagnitudeBin.magnitude_upper)
        .where(ForecastCellMagnitudeBin.forecast_run_id == run.id)
        .distinct()
        .order_by(ForecastCellMagnitudeBin.magnitude_lower)
    ).all()
    if not bin_rows:
        raise HTTPException(status_code=404, detail="forecast run has no cell/bin rows")
    available_lowers = [lower for lower, _upper in bin_rows]
    if magnitude_lower is not None:
        selected = magnitude_lower
    else:
        # Bins whose lower edge sits below the run's reference magnitude
        # are always not_estimable (forecast-contract.md's "target
        # threshold below Mc" rule) and would return zero cells -- default
        # to the smallest bin at/above Mc instead of the smallest bin
        # overall.
        estimable_lowers = [lower for lower in available_lowers if lower >= run.reference_magnitude]
        selected = estimable_lowers[0] if estimable_lowers else available_lowers[0]
    if selected not in available_lowers:
        raise HTTPException(
            status_code=422, detail=f"magnitude_lower must be one of {available_lowers}"
        )

    cell_statement = (
        select(ForecastCellMagnitudeBin, SeismicCell.center_latitude, SeismicCell.center_longitude)
        .join(SeismicCell, SeismicCell.id == ForecastCellMagnitudeBin.cell_id)
        .where(
            ForecastCellMagnitudeBin.forecast_run_id == run.id,
            ForecastCellMagnitudeBin.magnitude_lower == selected,
            ForecastCellMagnitudeBin.support_state == "estimable",
        )
        .order_by(ForecastCellMagnitudeBin.expected_count.desc())
        .limit(limit)
    )
    cells = [
        ForecastCellResponse(
            cell_id=bin_row.cell_id,
            center_latitude=center_latitude,
            center_longitude=center_longitude,
            magnitude_lower=bin_row.magnitude_lower,
            magnitude_upper=bin_row.magnitude_upper,
            expected_count=bin_row.expected_count,
            probability_at_least_one=bin_row.probability_at_least_one,
        )
        for bin_row, center_latitude, center_longitude in session.execute(cell_statement)
    ]
    return ForecastRunDetailResponse(
        id=run.id,
        issued_at=run.issued_at,
        validity_start=run.validity_start,
        validity_end=run.validity_end,
        horizon_id=run.horizon_id,
        reference_magnitude=run.reference_magnitude,
        b_value_used=run.b_value_used,
        calibration_status=run.calibration_status,
        method_version=run.method_version,
        background_rate_run_id=run.background_rate_run_id,
        background_spatial_model=run.diagnostics_json.get(
            "background_spatial_model", "homogeneous_area_weighted"
        ),
        etas_stability=run.diagnostics_json.get("etas_stability", {}),
        predictive_catalog_simulation=run.diagnostics_json.get("predictive_catalog_simulation"),
        magnitude_bins=[
            ForecastMagnitudeBinResponse(lower=lower, upper=upper) for lower, upper in bin_rows
        ],
        selected_magnitude_lower=selected,
        cell_count_total=run.cell_count,
        cells=cells,
    )


def _selected_magnitude_lower(
    run: ForecastRun, available_lowers: list[float], magnitude_lower: float | None
) -> float:
    if magnitude_lower is not None:
        if magnitude_lower not in available_lowers:
            raise HTTPException(
                status_code=422, detail=f"magnitude_lower must be one of {available_lowers}"
            )
        return magnitude_lower
    estimable_lowers = [lower for lower in available_lowers if lower >= run.reference_magnitude]
    return estimable_lowers[0] if estimable_lowers else available_lowers[0]


@router.get("/forecasts/{forecast_run_id}/places", response_model=ForecastPlacesResponse)
def forecast_places(
    forecast_run_id: uuid.UUID,
    session: SessionDependency,
    magnitude_lower: float | None = None,
    radius_km: float = Query(default=DEFAULT_RADIUS_KM, ge=10, le=150),
) -> ForecastPlacesResponse:
    """City-neighborhood readout of an issued forecast.

    Sums expected counts of estimable cells whose centers fall within
    ``radius_km`` of each named city, then converts the sum to a Poisson
    P(at least one). The number inherits the run's calibration_status; it
    is not a calibrated civil-protection probability.
    """
    run = session.get(ForecastRun, forecast_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="forecast run not found")
    bin_rows = session.execute(
        select(ForecastCellMagnitudeBin.magnitude_lower, ForecastCellMagnitudeBin.magnitude_upper)
        .where(ForecastCellMagnitudeBin.forecast_run_id == run.id)
        .distinct()
        .order_by(ForecastCellMagnitudeBin.magnitude_lower)
    ).all()
    if not bin_rows:
        raise HTTPException(status_code=404, detail="forecast run has no cell/bin rows")
    available_lowers = [lower for lower, _upper in bin_rows]
    selected = _selected_magnitude_lower(run, available_lowers, magnitude_lower)
    selected_upper = next(upper for lower, upper in bin_rows if lower == selected)

    places_out: list[PlaceForecastResponse] = []
    for place in PLACES:
        south, north, west, east = bounding_box(
            float(place["latitude"]), float(place["longitude"]), radius_km
        )
        nearby = session.execute(
            select(
                SeismicCell.center_latitude,
                SeismicCell.center_longitude,
                ForecastCellMagnitudeBin.expected_count,
            )
            .join(SeismicCell, SeismicCell.id == ForecastCellMagnitudeBin.cell_id)
            .where(
                ForecastCellMagnitudeBin.forecast_run_id == run.id,
                ForecastCellMagnitudeBin.magnitude_lower == selected,
                ForecastCellMagnitudeBin.support_state == "estimable",
                ForecastCellMagnitudeBin.expected_count.is_not(None),
                SeismicCell.center_latitude.between(south, north),
                SeismicCell.center_longitude.between(west, east),
            )
        ).all()
        estimate = estimate_place(
            [(lat, lon, expected) for lat, lon, expected in nearby],
            place,
            radius_km=radius_km,
        )
        places_out.append(
            PlaceForecastResponse(
                place_id=estimate.place_id,
                name=estimate.name,
                latitude=estimate.latitude,
                longitude=estimate.longitude,
                radius_km=estimate.radius_km,
                cell_count=estimate.cell_count,
                expected_count=estimate.expected_count,
                probability_at_least_one=estimate.probability_at_least_one,
            )
        )

    return ForecastPlacesResponse(
        forecast_run_id=run.id,
        magnitude_lower=selected,
        magnitude_upper=selected_upper,
        horizon_id=run.horizon_id,
        calibration_status=run.calibration_status,
        places=places_out,
    )


@router.get("/seismicity/model-summary", response_model=SeismicityModelSummaryResponse)
def seismicity_model_summary(session: SessionDependency) -> SeismicityModelSummaryResponse:
    """The most recently converged spatiotemporal ETAS fit and the exact
    Gutenberg-Richter/completeness estimates it cites -- the one "current
    default model" a dashboard's model card wants, resolved by recency
    rather than a hardcoded id, since which chain is the presented default
    can change as new fits are added.
    """
    etas = session.scalar(
        select(SpatiotemporalEtasEstimate)
        .where(SpatiotemporalEtasEstimate.converged.is_(True))
        .order_by(SpatiotemporalEtasEstimate.created_at.desc())
        .limit(1)
    )
    if etas is None:
        raise HTTPException(status_code=404, detail="no converged spatiotemporal ETAS estimate yet")
    gutenberg_richter = session.scalar(
        select(GutenbergRichterEstimate)
        .where(GutenbergRichterEstimate.completeness_estimate_id == etas.completeness_estimate_id)
        .order_by(GutenbergRichterEstimate.created_at.desc())
        .limit(1)
    )
    completeness = session.get(CompletenessEstimate, etas.completeness_estimate_id)
    if gutenberg_richter is None or completeness is None:
        raise HTTPException(status_code=404, detail="ETAS estimate lineage incomplete")
    return SeismicityModelSummaryResponse(
        completeness_estimate_id=completeness.id,
        mc_value=completeness.mc_value,
        magnitude_type=completeness.magnitude_type,
        completeness_window_start=completeness.start_time,
        completeness_window_end=completeness.end_time,
        completeness_event_count=completeness.event_count,
        gutenberg_richter_estimate_id=gutenberg_richter.id,
        b_value=gutenberg_richter.b_value,
        b_value_standard_error=gutenberg_richter.b_value_standard_error,
        events_at_or_above_mc=gutenberg_richter.events_at_or_above_mc,
        spatiotemporal_etas_estimate_id=etas.id,
        mu_per_day=etas.mu_per_day,
        k0=etas.k0,
        alpha=etas.alpha,
        c_days=etas.c_days,
        p_exponent=etas.p_exponent,
        d0_km=etas.d0_km,
        gamma=etas.gamma,
        q_exponent=etas.q_exponent,
        converged=etas.converged,
    )
