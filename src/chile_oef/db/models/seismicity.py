import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chile_oef.db.base import Base, utc_now


class CompletenessEstimate(Base):
    """Append-only Mc estimate. A recalculation inserts a new row; it never
    updates or deletes a previous one, mirroring the forecast immutability
    invariant in docs/scientific-methodology.md.
    """

    __tablename__ = "completeness_estimates"
    __table_args__ = (
        CheckConstraint("event_count >= 0", name="event_count_non_negative"),
        Index(
            "ix_completeness_estimates_window",
            "magnitude_type",
            "start_time",
            "end_time",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    min_latitude: Mapped[float | None] = mapped_column(Float)
    max_latitude: Mapped[float | None] = mapped_column(Float)
    min_longitude: Mapped[float | None] = mapped_column(Float)
    max_longitude: Mapped[float | None] = mapped_column(Float)
    magnitude_type: Mapped[str] = mapped_column(String(16), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    support_state: Mapped[str] = mapped_column(String(32), nullable=False)
    mc_value: Mapped[float | None] = mapped_column(Float)
    bin_width_magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    catalog_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class GutenbergRichterEstimate(Base):
    """Append-only b-value estimate. Always cites the specific
    CompletenessEstimate row whose mc_value it used -- docs/completeness.md:
    "Every downstream statistic stores the Mc result it used." The window,
    magnitude type, and spatial filters are copied from that row rather than
    accepted as independent arguments, so a b-value can never be computed
    against a Mc from a different window or region by mistake.
    """

    __tablename__ = "gutenberg_richter_estimates"
    __table_args__ = (
        CheckConstraint("event_count >= 0", name="event_count_non_negative"),
        CheckConstraint("events_at_or_above_mc >= 0", name="events_at_or_above_mc_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    completeness_estimate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("completeness_estimates.id"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    min_latitude: Mapped[float | None] = mapped_column(Float)
    max_latitude: Mapped[float | None] = mapped_column(Float)
    min_longitude: Mapped[float | None] = mapped_column(Float)
    max_longitude: Mapped[float | None] = mapped_column(Float)
    magnitude_type: Mapped[str] = mapped_column(String(16), nullable=False)
    mc_used: Mapped[float] = mapped_column(Float, nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    events_at_or_above_mc: Mapped[int] = mapped_column(Integer, nullable=False)
    support_state: Mapped[str] = mapped_column(String(32), nullable=False)
    b_value: Mapped[float | None] = mapped_column(Float)
    b_value_standard_error: Mapped[float | None] = mapped_column(Float)
    a_value: Mapped[float | None] = mapped_column(Float)
    catalog_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SeismicityDeclusteringRun(Base):
    """Append-only declustering run. Always cites the specific
    GutenbergRichterEstimate row whose b_value and Mc it used -- same
    provenance discipline as GutenbergRichterEstimate citing
    CompletenessEstimate.
    """

    __tablename__ = "seismicity_declustering_runs"
    __table_args__ = (CheckConstraint("event_count >= 0", name="event_count_non_negative"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    gutenberg_richter_estimate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gutenberg_richter_estimates.id"), nullable=False
    )
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    min_latitude: Mapped[float | None] = mapped_column(Float)
    max_latitude: Mapped[float | None] = mapped_column(Float)
    min_longitude: Mapped[float | None] = mapped_column(Float)
    max_longitude: Mapped[float | None] = mapped_column(Float)
    magnitude_type: Mapped[str] = mapped_column(String(16), nullable=False)
    minimum_magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    b_value_used: Mapped[float] = mapped_column(Float, nullable=False)
    fractal_dimension: Mapped[float] = mapped_column(Float, nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    classified_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    background_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    log_eta_threshold: Mapped[float | None] = mapped_column(Float)
    catalog_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EventDeclusteringClassification(Base):
    """Append-only, one row per event per declustering run."""

    __tablename__ = "event_declustering_classifications"
    __table_args__ = (
        Index(
            "ix_event_declustering_classifications_run",
            "declustering_run_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    declustering_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seismicity_declustering_runs.id"), nullable=False
    )
    event_revision_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("event_revisions.id"), nullable=False
    )
    parent_event_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("event_revisions.id")
    )
    log10_eta: Mapped[float | None] = mapped_column(Float)
    is_background: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SeismicityBackgroundRateRun(Base):
    """Append-only smoothed background-rate run. Always cites the specific
    SeismicityDeclusteringRun whose background subset it smoothed, and the
    SpatialGrid (Phase 2) it was evaluated on.
    """

    __tablename__ = "seismicity_background_rate_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    declustering_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seismicity_declustering_runs.id"), nullable=False
    )
    grid_id: Mapped[str] = mapped_column(ForeignKey("spatial_grids.id"), nullable=False)
    k_nearest_neighbors: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_bandwidth_km: Mapped[float] = mapped_column(Float, nullable=False)
    observation_duration_days: Mapped[float] = mapped_column(Float, nullable=False)
    background_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    catalog_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class SeismicCellBackgroundRate(Base):
    """Append-only, one row per grid cell per background-rate run."""

    __tablename__ = "seismic_cell_background_rates"
    __table_args__ = (Index("ix_seismic_cell_background_rates_run", "background_rate_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    background_rate_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("seismicity_background_rate_runs.id"), nullable=False
    )
    cell_id: Mapped[str] = mapped_column(ForeignKey("seismic_cells.id"), nullable=False)
    density_per_km2: Mapped[float] = mapped_column(Float, nullable=False)
    rate_per_year: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
