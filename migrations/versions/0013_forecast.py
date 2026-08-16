"""forecast runs and per-cell magnitude-bin forecasts

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_runs",
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
        sa.Column("supersedes_forecast_run_id", sa.Uuid(), sa.ForeignKey("forecast_runs.id")),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validity_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("validity_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_id", sa.String(16), nullable=False),
        sa.Column("reference_magnitude", sa.Float(), nullable=False),
        sa.Column("b_value_used", sa.Float(), nullable=False),
        sa.Column("region_area_km2", sa.Float(), nullable=False),
        sa.Column("input_catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("cell_count", sa.Integer(), nullable=False),
        sa.Column("magnitude_bin_count", sa.Integer(), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("cell_count >= 0", name="cell_count_non_negative"),
    )
    op.create_index("ix_forecast_runs_issued_at", "forecast_runs", ["issued_at"])

    op.create_table(
        "forecast_cell_magnitude_bins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("forecast_run_id", sa.Uuid(), sa.ForeignKey("forecast_runs.id"), nullable=False),
        sa.Column("cell_id", sa.String(180), sa.ForeignKey("seismic_cells.id"), nullable=False),
        sa.Column("magnitude_lower", sa.Float(), nullable=False),
        sa.Column("magnitude_upper", sa.Float()),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("expected_count", sa.Float()),
        sa.Column("probability_at_least_one", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_forecast_cell_magnitude_bins_run",
        "forecast_cell_magnitude_bins",
        ["forecast_run_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_forecast_cell_magnitude_bins_run", table_name="forecast_cell_magnitude_bins")
    op.drop_table("forecast_cell_magnitude_bins")
    op.drop_index("ix_forecast_runs_issued_at", table_name="forecast_runs")
    op.drop_table("forecast_runs")
