"""walk-forward evaluation runs and per-fold scores

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evaluation_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "spatiotemporal_etas_estimate_id",
            sa.Uuid(),
            sa.ForeignKey("spatiotemporal_etas_estimates.id"),
            nullable=False,
        ),
        sa.Column(
            "gutenberg_richter_estimate_id",
            sa.Uuid(),
            sa.ForeignKey("gutenberg_richter_estimates.id"),
            nullable=False,
        ),
        sa.Column("grid_id", sa.String(128), sa.ForeignKey("spatial_grids.id"), nullable=False),
        sa.Column("horizon_id", sa.String(16), nullable=False),
        sa.Column("walk_forward_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("walk_forward_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("step_seconds", sa.Float(), nullable=False),
        sa.Column("adjudication_delay_seconds", sa.Float(), nullable=False),
        sa.Column("csep_alpha", sa.Float(), nullable=False),
        sa.Column("n_simulations", sa.Integer(), nullable=False),
        sa.Column("bootstrap_resamples", sa.Integer(), nullable=False),
        sa.Column("bootstrap_confidence_level", sa.Float(), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("fold_count", sa.Integer(), nullable=False),
        sa.Column("zero_observed_fold_count", sa.Integer(), nullable=False),
        sa.Column("aggregate_scores_json", postgresql.JSONB(), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("fold_count >= 0", name="evaluation_fold_count_non_negative"),
    )
    op.create_index(
        "ix_evaluation_runs_walk_forward_start", "evaluation_runs", ["walk_forward_start"]
    )

    op.create_table(
        "evaluation_fold_scores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "evaluation_run_id", sa.Uuid(), sa.ForeignKey("evaluation_runs.id"), nullable=False
        ),
        sa.Column("forecast_run_id", sa.Uuid(), sa.ForeignKey("forecast_runs.id"), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validity_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validity_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_event_count", sa.Integer(), nullable=False),
        sa.Column("excluded_not_estimable_count", sa.Integer(), nullable=False),
        sa.Column("scores_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_evaluation_fold_scores_run", "evaluation_fold_scores", ["evaluation_run_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_evaluation_fold_scores_run", table_name="evaluation_fold_scores")
    op.drop_table("evaluation_fold_scores")
    op.drop_index("ix_evaluation_runs_walk_forward_start", table_name="evaluation_runs")
    op.drop_table("evaluation_runs")
