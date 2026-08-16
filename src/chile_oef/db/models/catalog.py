import uuid
from datetime import datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from chile_oef.db.base import Base, RecordedAtMixin, utc_now


class CatalogSource(Base, RecordedAtMixin):
    __tablename__ = "catalog_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    authority: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    license_id: Mapped[str | None] = mapped_column(String(128))
    attribution: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    endpoints: Mapped[list["SourceEndpoint"]] = relationship(back_populates="source")
    source_events: Mapped[list["SourceEvent"]] = relationship(back_populates="source")


class SourceEndpoint(Base, RecordedAtMixin):
    __tablename__ = "source_endpoints"
    __table_args__ = (UniqueConstraint("source_id", "kind", "url"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    source: Mapped[CatalogSource] = relationship(back_populates="endpoints")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    request_url: Mapped[str] = mapped_column(Text, nullable=False)
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    revisions_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)


class RawArtifact(Base):
    __tablename__ = "raw_artifacts"
    __table_args__ = (UniqueConstraint("source_id", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    media_type: Mapped[str | None] = mapped_column(String(255))
    http_status: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class IngestionArtifact(Base):
    """Associates every retrieval run with content, including repeated content."""

    __tablename__ = "ingestion_artifacts"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "raw_artifact_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_runs.id"), nullable=False
    )
    raw_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_artifacts.id"), nullable=False
    )


class SourceEvent(Base, RecordedAtMixin):
    __tablename__ = "source_events"
    __table_args__ = (UniqueConstraint("source_id", "source_event_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)

    source: Mapped[CatalogSource] = relationship(back_populates="source_events")
    revisions: Mapped[list["EventRevision"]] = relationship(back_populates="source_event")


class EventRevision(Base, RecordedAtMixin):
    __tablename__ = "event_revisions"
    __table_args__ = (
        UniqueConstraint("source_event_id", "revision_hash"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        Index("ix_event_revisions_event_time", "event_time"),
        Index("ix_event_revisions_available_at", "available_at"),
        Index("ix_event_revisions_geometry_gist", "geometry", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_events.id"), nullable=False
    )
    raw_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_artifacts.id"), nullable=False
    )
    revision_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    depth_km: Mapped[float | None] = mapped_column(Float)
    magnitude: Mapped[float | None] = mapped_column(Float)
    magnitude_type: Mapped[str | None] = mapped_column(String(32))
    place: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(String(32))
    location_uncertainty_km: Mapped[float | None] = mapped_column(Float)
    depth_uncertainty_km: Mapped[float | None] = mapped_column(Float)
    magnitude_uncertainty: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)
    parsed_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)

    source_event: Mapped[SourceEvent] = relationship(back_populates="revisions")
    quality_logs: Mapped[list["DataQualityLog"]] = relationship(back_populates="revision")


class DataQualityLog(Base, RecordedAtMixin):
    __tablename__ = "data_quality_logs"
    __table_args__ = (UniqueConstraint("event_revision_id", "flag"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_revisions.id"), nullable=False
    )
    flag: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    detail: Mapped[str | None] = mapped_column(Text)

    revision: Mapped[EventRevision] = relationship(back_populates="quality_logs")


class CanonicalEvent(Base, RecordedAtMixin):
    __tablename__ = "canonical_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")


class CanonicalEventMembership(Base, RecordedAtMixin):
    __tablename__ = "canonical_event_memberships"
    __table_args__ = (UniqueConstraint("canonical_event_id", "source_event_id", "valid_from"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    canonical_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canonical_events.id"), nullable=False
    )
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_events.id"), nullable=False
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    match_probability: Mapped[float] = mapped_column(Float, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)


class DeduplicationCandidate(Base, RecordedAtMixin):
    __tablename__ = "deduplication_candidates"
    __table_args__ = (
        UniqueConstraint("left_event_revision_id", "right_event_revision_id", "method_version"),
        CheckConstraint("match_probability >= 0 AND match_probability <= 1", name="probability"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    left_event_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_revisions.id"), nullable=False
    )
    right_event_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_revisions.id"), nullable=False
    )
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    match_probability: Mapped[float] = mapped_column(Float, nullable=False)
    time_delta_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    magnitude_delta: Mapped[float | None] = mapped_column(Float)
    depth_delta_km: Mapped[float | None] = mapped_column(Float)
    decision: Mapped[str] = mapped_column(String(32), nullable=False, default="candidate")


class DatasetVersion(Base):
    """Immutable, named as-of selection of event revisions and source artifacts."""

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint("dataset_id", "version"),
        UniqueConstraint("manifest_sha256"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    git_commit: Mapped[str | None] = mapped_column(String(64))


class DatasetArtifact(Base):
    __tablename__ = "dataset_artifacts"
    __table_args__ = (UniqueConstraint("dataset_version_id", "raw_artifact_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=False
    )
    raw_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_artifacts.id"), nullable=False
    )


class DatasetEventRevision(Base):
    __tablename__ = "dataset_event_revisions"
    __table_args__ = (UniqueConstraint("dataset_version_id", "event_revision_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dataset_versions.id"), nullable=False
    )
    event_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_revisions.id"), nullable=False
    )
