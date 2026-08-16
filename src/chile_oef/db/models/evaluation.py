import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from chile_oef.db.base import Base, utc_now


class EvaluationRun(Base):
    """Append-only walk-forward CSEP/pyCSEP-style evaluation
    (docs/backtesting.md, config/evaluation-protocol.yaml): one execution
    of the walk-forward replay over
    `[walk_forward_start, walk_forward_end)`, citing the specific
    spatiotemporal ETAS and Gutenberg-Richter estimates under test. Each
    issue time in that range produces one real `ForecastRun` (via
    `ForecastService.issue_forecast`, same immutability/lineage rules as
    every other forecast) and one `EvaluationFoldScore`. Scalar scores are
    aggregated across folds by time-block bootstrap
    (`aggregate_scores_json`); nothing here is re-computed or overwritten
    after the run finishes -- a re-run is a new `EvaluationRun` row.
    """

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        CheckConstraint("fold_count >= 0", name="evaluation_fold_count_non_negative"),
        Index("ix_evaluation_runs_walk_forward_start", "walk_forward_start"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    spatiotemporal_etas_estimate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("spatiotemporal_etas_estimates.id"), nullable=False
    )
    gutenberg_richter_estimate_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gutenberg_richter_estimates.id"), nullable=False
    )
    grid_id: Mapped[str] = mapped_column(ForeignKey("spatial_grids.id"), nullable=False)
    horizon_id: Mapped[str] = mapped_column(String(16), nullable=False)
    walk_forward_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    walk_forward_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    step_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    adjudication_delay_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    csep_alpha: Mapped[float] = mapped_column(Float, nullable=False)
    n_simulations: Mapped[int] = mapped_column(Integer, nullable=False)
    bootstrap_resamples: Mapped[int] = mapped_column(Integer, nullable=False)
    bootstrap_confidence_level: Mapped[float] = mapped_column(Float, nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    fold_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # Folds with zero observed events during the horizon. Not dropped from
    # fold_count or aggregate scoring -- the N-test and count/binary scores
    # all remain well-defined at zero -- but the S-test and M-test are
    # conditional on a nonzero observed total, so those two specific tests
    # are `not_estimable` for exactly these folds (see
    # chile_oef.evaluation.csep_tests._normalized_marginal_test).
    zero_observed_fold_count: Mapped[int] = mapped_column(Integer, nullable=False)
    aggregate_scores_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    diagnostics_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )


class EvaluationFoldScore(Base):
    """Append-only, one row per walk-forward issue time. Cites the real,
    immutable `ForecastRun` this fold scored -- scores are always
    traceable back to the exact persisted forecast artifact they were
    computed from, not recomputed ad hoc. `scores_json` holds every
    per-fold scalar and CSEP test result (documented in
    `chile_oef.evaluation.replay`); it is intentionally one flexible JSONB
    column rather than ~20 dedicated float columns, since the score
    registry is versioned externally in config/evaluation-protocol.yaml
    and is expected to grow.
    """

    __tablename__ = "evaluation_fold_scores"
    __table_args__ = (Index("ix_evaluation_fold_scores_run", "evaluation_run_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    evaluation_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evaluation_runs.id"), nullable=False
    )
    forecast_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("forecast_runs.id"), nullable=False
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validity_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    validity_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_event_count: Mapped[int] = mapped_column(Integer, nullable=False)
    excluded_not_estimable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    scores_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
