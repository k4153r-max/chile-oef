"""Modified Omori-Utsu aftershock sequence estimates

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "modified_omori_sequence_estimates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "declustering_run_id",
            sa.Uuid(),
            sa.ForeignKey("seismicity_declustering_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "root_event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("support_state", sa.String(32), nullable=False),
        sa.Column("observation_duration_days", sa.Float(), nullable=False),
        sa.Column("k_productivity", sa.Float()),
        sa.Column("c_days", sa.Float()),
        sa.Column("p_exponent", sa.Float()),
        sa.Column("converged", sa.Boolean(), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_count >= 0", name="event_count_non_negative"),
    )
    op.create_index(
        "ix_modified_omori_sequence_estimates_run",
        "modified_omori_sequence_estimates",
        ["declustering_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_modified_omori_sequence_estimates_run",
        table_name="modified_omori_sequence_estimates",
    )
    op.drop_table("modified_omori_sequence_estimates")
