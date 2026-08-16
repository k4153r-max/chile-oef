"""magnitude-of-completeness estimates

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "completeness_estimates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_latitude", sa.Float()),
        sa.Column("max_latitude", sa.Float()),
        sa.Column("min_longitude", sa.Float()),
        sa.Column("max_longitude", sa.Float()),
        sa.Column("magnitude_type", sa.String(16), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("mc_value", sa.Float()),
        sa.Column("bin_width_magnitude", sa.Float(), nullable=False),
        sa.Column("catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_count >= 0", name="event_count_non_negative"),
    )
    op.create_index(
        "ix_completeness_estimates_window",
        "completeness_estimates",
        ["magnitude_type", "start_time", "end_time"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_completeness_estimates_window",
        table_name="completeness_estimates",
    )
    op.drop_table("completeness_estimates")
