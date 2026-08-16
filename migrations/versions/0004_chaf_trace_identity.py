"""use source record ordinal as CHAF trace identity

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "fault_traces",
        sa.Column("source_record_index", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY release_id
                       ORDER BY recorded_at, id
                   ) AS source_record_index
            FROM fault_traces
        )
        UPDATE fault_traces AS target
        SET source_record_index = ranked.source_record_index
        FROM ranked
        WHERE target.id = ranked.id
        """
    )
    op.alter_column("fault_traces", "source_record_index", nullable=False)
    op.drop_constraint("uq_fault_traces_release_id", "fault_traces", type_="unique")
    op.create_unique_constraint(
        "uq_fault_traces_release_id",
        "fault_traces",
        ["release_id", "source_record_index"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_fault_traces_release_id", "fault_traces", type_="unique")
    op.create_unique_constraint(
        "uq_fault_traces_release_id",
        "fault_traces",
        ["release_id", "external_id"],
    )
    op.drop_column("fault_traces", "source_record_index")
