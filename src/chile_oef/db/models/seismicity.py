import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Uuid
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
