"""spatiotemporal ETAS estimates

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "spatiotemporal_etas_estimates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "completeness_estimate_id",
            sa.Uuid(),
            sa.ForeignKey("completeness_estimates.id"),
            nullable=False,
        ),
        sa.Column(
            "initial_guess_source_id",
            sa.Uuid(),
            sa.ForeignKey("modified_omori_sequence_estimates.id"),
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_latitude", sa.Float(), nullable=False),
        sa.Column("max_latitude", sa.Float(), nullable=False),
        sa.Column("min_longitude", sa.Float(), nullable=False),
        sa.Column("max_longitude", sa.Float(), nullable=False),
        sa.Column("region_area_km2", sa.Float(), nullable=False),
        sa.Column("magnitude_type", sa.String(16), nullable=False),
        sa.Column("reference_magnitude", sa.Float(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("observation_duration_days", sa.Float(), nullable=False),
        sa.Column("mu_per_day", sa.Float()),
        sa.Column("k0", sa.Float()),
        sa.Column("alpha", sa.Float()),
        sa.Column("c_days", sa.Float()),
        sa.Column("p_exponent", sa.Float()),
        sa.Column("d0_km", sa.Float()),
        sa.Column("gamma", sa.Float()),
        sa.Column("q_exponent", sa.Float()),
        sa.Column("converged", sa.Boolean(), nullable=False),
        sa.Column("restarts_converged", sa.Integer(), nullable=False),
        sa.Column("log_likelihood", sa.Float()),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_count >= 0", name="event_count_non_negative"),
    )


def downgrade() -> None:
    op.drop_table("spatiotemporal_etas_estimates")
