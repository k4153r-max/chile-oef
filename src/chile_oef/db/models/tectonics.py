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
from sqlalchemy.orm import Mapped, mapped_column

from chile_oef.db.base import Base, RecordedAtMixin, utc_now


class TectonicRelease(Base, RecordedAtMixin):
    __tablename__ = "tectonic_releases"
    __table_args__ = (UniqueConstraint("source_id", "release_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    release_id: Mapped[str] = mapped_column(String(128), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    doi: Mapped[str | None] = mapped_column(Text)
    license_id: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="building")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TectonicAsset(Base, RecordedAtMixin):
    __tablename__ = "tectonic_assets"
    __table_args__ = (UniqueConstraint("release_id", "asset_type"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tectonic_releases.id"), nullable=False
    )
    raw_artifact_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_artifacts.id"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class SlabNode(Base):
    __tablename__ = "slab_nodes"
    __table_args__ = (
        UniqueConstraint("release_id", "longitude_index", "latitude_index"),
        Index("ix_slab_nodes_geometry_gist", "geometry", postgresql_using="gist"),
        Index("ix_slab_nodes_release_grid", "release_id", "longitude_index", "latitude_index"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tectonic_releases.id"), nullable=False
    )
    longitude_index: Mapped[int] = mapped_column(Integer, nullable=False)
    latitude_index: Mapped[int] = mapped_column(Integer, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    depth_km: Mapped[float] = mapped_column(Float, nullable=False)
    dip_degrees: Mapped[float | None] = mapped_column(Float)
    strike_degrees: Mapped[float | None] = mapped_column(Float)
    thickness_km: Mapped[float | None] = mapped_column(Float)
    uncertainty_km: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any] = mapped_column(Geometry("POINT", srid=4326), nullable=False)


class FaultTrace(Base, RecordedAtMixin):
    __tablename__ = "fault_traces"
    __table_args__ = (
        UniqueConstraint("release_id", "source_record_index"),
        Index("ix_fault_traces_geometry_gist", "geometry", postgresql_using="gist"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tectonic_releases.id"), nullable=False
    )
    source_record_index: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fault_system: Mapped[str | None] = mapped_column(String(128))
    fault_name: Mapped[str | None] = mapped_column(Text)
    trace_name: Mapped[str | None] = mapped_column(Text)
    trace_type: Mapped[str | None] = mapped_column(String(64))
    activity_class: Mapped[str | None] = mapped_column(String(64))
    strike_degrees: Mapped[float | None] = mapped_column(Float)
    dip_degrees: Mapped[float | None] = mapped_column(Float)
    rake_degrees: Mapped[float | None] = mapped_column(Float)
    length_km: Mapped[float | None] = mapped_column(Float)
    geometry: Mapped[Any] = mapped_column(Geometry("MULTILINESTRING", srid=4326), nullable=False)
    properties_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class SpatialGrid(Base):
    __tablename__ = "spatial_grids"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    resolution_degrees: Mapped[float] = mapped_column(Float, nullable=False)
    min_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    max_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    min_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    max_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    crs: Mapped[str] = mapped_column(String(32), nullable=False, default="EPSG:4326")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    definition_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class SeismicCell(Base):
    __tablename__ = "seismic_cells"
    __table_args__ = (
        UniqueConstraint("grid_id", "row_index", "column_index"),
        Index("ix_seismic_cells_geometry_gist", "geometry", postgresql_using="gist"),
    )

    id: Mapped[str] = mapped_column(String(180), primary_key=True)
    grid_id: Mapped[str] = mapped_column(ForeignKey("spatial_grids.id"), nullable=False)
    row_index: Mapped[int] = mapped_column(Integer, nullable=False)
    column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    center_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    center_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    geometry: Mapped[Any] = mapped_column(Geometry("POLYGON", srid=4326), nullable=False)


class EventTectonicClassification(Base):
    __tablename__ = "event_tectonic_classifications"
    __table_args__ = (
        UniqueConstraint(
            "event_revision_id",
            "slab_release_id",
            "fault_release_id",
            "method_version",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "max_probability >= 0 AND max_probability <= 1",
            name="max_probability_range",
        ),
        Index("ix_event_tectonic_classifications_label", "label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_revisions.id"), nullable=False
    )
    slab_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tectonic_releases.id"), nullable=False
    )
    fault_release_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tectonic_releases.id"))
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    max_probability: Mapped[float] = mapped_column(Float, nullable=False)
    slab_depth_km: Mapped[float | None] = mapped_column(Float)
    signed_vertical_residual_km: Mapped[float | None] = mapped_column(Float)
    signed_normal_distance_km: Mapped[float | None] = mapped_column(Float)
    horizontal_fault_distance_km: Mapped[float | None] = mapped_column(Float)
    probabilities_json: Mapped[dict[str, float]] = mapped_column(JSONB, nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
