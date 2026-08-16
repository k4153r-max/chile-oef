"""Gutenberg-Richter b-value estimates

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gutenberg_richter_estimates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "completeness_estimate_id",
            sa.Uuid(),
            sa.ForeignKey("completeness_estimates.id"),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_latitude", sa.Float()),
        sa.Column("max_latitude", sa.Float()),
        sa.Column("min_longitude", sa.Float()),
        sa.Column("max_longitude", sa.Float()),
        sa.Column("magnitude_type", sa.String(16), nullable=False),
        sa.Column("mc_used", sa.Float(), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("events_at_or_above_mc", sa.Integer(), nullable=False),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("b_value", sa.Float()),
        sa.Column("b_value_standard_error", sa.Float()),
        sa.Column("a_value", sa.Float()),
        sa.Column("catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_count >= 0", name="event_count_non_negative"),
        sa.CheckConstraint("events_at_or_above_mc >= 0", name="events_at_or_above_mc_nonneg"),
    )


def downgrade() -> None:
    op.drop_table("gutenberg_richter_estimates")
