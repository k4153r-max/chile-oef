import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from chile_oef.db.base import Base, utc_now


class HistoricalBackfillSlice(Base):
    """Tracks one time-partitioned slice of a bulk historical backfill
    (`chile_oef.ingestion.historical_backfill`) -- distinct from
    `IngestionRun`, which records one raw fetch, not "did this business-
    level backfill slice complete." A slice can be retried across multiple
    `IngestionRun`s; only the run that actually succeeded is cited here.
    Re-running a backfill checks this table (matched on source, exact
    time range, magnitude floor and bounding box) rather than parsing
    `IngestionRun.request_url` strings, so resumability does not depend on
    HTTP query-parameter encoding staying byte-for-byte stable.
    """

    __tablename__ = "historical_backfill_slices"
    __table_args__ = (
        Index(
            "ix_historical_backfill_slices_lookup",
            "source_id",
            "start_time",
            "end_time",
            "min_magnitude",
            "min_latitude",
            "max_latitude",
            "min_longitude",
            "max_longitude",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("catalog_sources.id"), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    min_magnitude: Mapped[float | None] = mapped_column(Float)
    min_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    max_latitude: Mapped[float] = mapped_column(Float, nullable=False)
    min_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    max_longitude: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    event_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
