import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DISCLAIMER_ES = (
    "CHILE-OEF es una plataforma experimental de investigación que analiza patrones "
    "estadísticos de actividad sísmica. No predice terremotos de forma determinista "
    "y no reemplaza información oficial del Centro Sismológico Nacional, SENAPRED "
    "ni otras autoridades."
)


class QualityFlagResponse(BaseModel):
    flag: str
    severity: str
    detail: str | None


class EventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_id: uuid.UUID
    revision_id: uuid.UUID
    source_id: str
    source_event_identifier: str
    event_time: datetime
    received_at: datetime
    available_at: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    magnitude_type: str | None
    place: str | None
    status: str | None


class EventListResponse(BaseModel):
    data: list[EventResponse]
    as_of: datetime
    limit: int
    offset: int
    disclaimer: str = DISCLAIMER_ES


class EventRevisionResponse(BaseModel):
    revision_id: uuid.UUID
    source_id: str
    source_event_identifier: str
    revision_hash: str
    event_time: datetime
    source_updated_at: datetime | None
    received_at: datetime
    available_at: datetime
    latitude: float
    longitude: float
    depth_km: float | None
    magnitude: float | None
    magnitude_type: str | None
    place: str | None
    parser_version: str
    quality_flags: list[QualityFlagResponse]


class EventDetailResponse(BaseModel):
    canonical_id: uuid.UUID
    revisions: list[EventRevisionResponse]
    disclaimer: str = DISCLAIMER_ES


class HealthResponse(BaseModel):
    status: str
    database: str
    version: str


class SourceStatusResponse(BaseModel):
    source_id: str
    enabled: bool
    last_run_started_at: datetime | None
    last_run_finished_at: datetime | None
    last_run_status: str | None
    records_seen: int | None = Field(default=None, ge=0)
    revisions_inserted: int | None = Field(default=None, ge=0)


class RawArtifactResponse(BaseModel):
    source_id: str
    retrieved_at: datetime
    source_url: str
    storage_uri: str
    sha256: str
    byte_length: int = Field(ge=0)
    media_type: str | None
    http_status: int | None


class DatasetVersionResponse(BaseModel):
    dataset_id: str
    version: str
    as_of: datetime
    created_at: datetime
    manifest_sha256: str
    git_commit: str | None
    manifest: dict[str, Any]


class GridResponse(BaseModel):
    id: str
    resolution_degrees: float
    min_latitude: float
    max_latitude: float
    min_longitude: float
    max_longitude: float
    status: str
    definition_sha256: str
    metadata: dict[str, Any]


class CellResponse(BaseModel):
    id: str
    grid_id: str
    row_index: int
    column_index: int
    center_latitude: float
    center_longitude: float
    area_km2: float


class TectonicReleaseResponse(BaseModel):
    id: uuid.UUID
    source_id: str
    release_id: str
    title: str
    doi: str | None
    license_id: str
    status: str
    metadata: dict[str, Any]


class SlabSampleResponse(BaseModel):
    latitude: float
    longitude: float
    depth_km: float
    dip_degrees: float | None
    strike_degrees: float | None
    thickness_km: float | None
    uncertainty_km: float | None
    interpolation: str
    contributing_nodes: int


class TectonicClassificationResponse(BaseModel):
    id: uuid.UUID
    event_revision_id: uuid.UUID
    slab_release_id: uuid.UUID
    fault_release_id: uuid.UUID | None
    method_version: str
    calibration_status: str
    label: str
    max_probability: float = Field(ge=0, le=1)
    slab_depth_km: float | None
    signed_vertical_residual_km: float | None
    signed_normal_distance_km: float | None
    horizontal_fault_distance_km: float | None
    probabilities: dict[str, float]
    diagnostics: dict[str, Any]
    created_at: datetime
