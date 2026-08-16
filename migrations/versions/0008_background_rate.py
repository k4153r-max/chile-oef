"""smoothed adaptive-kernel background rate runs

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seismicity_background_rate_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "declustering_run_id",
            sa.Uuid(),
            sa.ForeignKey("seismicity_declustering_runs.id"),
            nullable=False,
        ),
        sa.Column("grid_id", sa.String(128), sa.ForeignKey("spatial_grids.id"), nullable=False),
        sa.Column("k_nearest_neighbors", sa.Integer(), nullable=False),
        sa.Column("minimum_bandwidth_km", sa.Float(), nullable=False),
        sa.Column("observation_duration_days", sa.Float(), nullable=False),
        sa.Column("background_event_count", sa.Integer(), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "seismic_cell_background_rates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "background_rate_run_id",
            sa.Uuid(),
            sa.ForeignKey("seismicity_background_rate_runs.id"),
            nullable=False,
        ),
        sa.Column("cell_id", sa.String(180), sa.ForeignKey("seismic_cells.id"), nullable=False),
        sa.Column("density_per_km2", sa.Float(), nullable=False),
        sa.Column("rate_per_year", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_seismic_cell_background_rates_run",
        "seismic_cell_background_rates",
        ["background_rate_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_seismic_cell_background_rates_run",
        table_name="seismic_cell_background_rates",
    )
    op.drop_table("seismic_cell_background_rates")
    op.drop_table("seismicity_background_rate_runs")
