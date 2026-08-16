"""seismic anomaly index (IAS) estimates

Revision ID: 0012
Revises: 0011
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seismic_anomaly_index_estimates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "temporal_etas_estimate_id",
            sa.Uuid(),
            sa.ForeignKey("temporal_etas_estimates.id"),
            nullable=False,
        ),
        sa.Column("evaluation_start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_window_days", sa.Float(), nullable=False),
        sa.Column("observed_count", sa.Integer(), nullable=False),
        sa.Column("expected_count", sa.Float(), nullable=False),
        sa.Column("deviance", sa.Float(), nullable=False),
        sa.Column("historical_window_count", sa.Integer(), nullable=False),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("ias_score", sa.Float()),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("seismic_anomaly_index_estimates")
