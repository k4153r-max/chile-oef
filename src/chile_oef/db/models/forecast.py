import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chile_oef.db.base import Base, utc_now


class ForecastRun(Base):
    """Append-only, immutable forecast issuance (docs/forecast-contract.md:
    "Published forecast rows cannot be updated or deleted through the
    application role. A recalculation creates a new run with
    supersedes_forecast_run_id."). Cites the specific SpatiotemporalEtasEstimate
    (rate model), GutenbergRichterEstimate (magnitude-bin allocation), and
    SpatialGrid used -- the same structural-provenance discipline as every
    other estimator in this project, now composed into one issuance.
    """

    __tablename__ = "forecast_runs"
    __table_args__ = (
        CheckConstraint("cell_count >= 0", name="cell_count_non_negative"),
        Index("ix_forecast_runs_issued_at", "issued_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    spatiotemporal_etas_estimate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spatiotemporal_etas_estimates.id"), nullable=False
    )
    gutenberg_richter_estimate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gutenberg_richter_estimates.id"), nullable=False
    )
    background_rate_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("seismicity_background_rate_runs.id")
    )
    grid_id: Mapped[str] = mapped_column(ForeignKey("spatial_grids.id"), nullable=False)
    supersedes_forecast_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("forecast_runs.id")
    )
    trigger_type: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validity_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validity_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_id: Mapped[str] = mapped_column(String(16), nullable=False)
    reference_magnitude: Mapped[float] = mapped_column(Float, nullable=False)
    b_value_used: Mapped[float] = mapped_column(Float, nullable=False)
    region_area_km2: Mapped[float] = mapped_column(Float, nullable=False)
    input_catalog_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    calibration_status: Mapped[str] = mapped_column(String(64), nullable=False)
    cell_count: Mapped[int] = mapped_column(Integer, nullable=False)
    magnitude_bin_count: Mapped[int] = mapped_column(Integer, nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class ForecastCellMagnitudeBin(Base):
    """Append-only, one row per grid cell per magnitude bin per forecast
    run. Rates are stored in non-overlapping magnitude bins
    (docs/forecast-contract.md); exceedance products are derived, not
    stored here.
    """

    __tablename__ = "forecast_cell_magnitude_bins"
    __table_args__ = (Index("ix_forecast_cell_magnitude_bins_run", "forecast_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id"), nullable=False
    )
    cell_id: Mapped[str] = mapped_column(ForeignKey("seismic_cells.id"), nullable=False)
    magnitude_lower: Mapped[float] = mapped_column(Float, nullable=False)
    magnitude_upper: Mapped[float | None] = mapped_column(Float)
    support_state: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_count: Mapped[float | None] = mapped_column(Float)
    probability_at_least_one: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
