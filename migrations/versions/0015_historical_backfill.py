"""historical backfill slice tracking

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "historical_backfill_slices",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_magnitude", sa.Float()),
        sa.Column("min_latitude", sa.Float(), nullable=False),
        sa.Column("max_latitude", sa.Float(), nullable=False),
        sa.Column("min_longitude", sa.Float(), nullable=False),
        sa.Column("max_longitude", sa.Float(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), sa.ForeignKey("ingestion_runs.id")),
        sa.Column("event_count", sa.Integer()),
        sa.Column("error_message", sa.Text()),
        sa.Column("attempted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_historical_backfill_slices_lookup",
        "historical_backfill_slices",
        [
            "source_id",
            "start_time",
            "end_time",
            "min_magnitude",
            "min_latitude",
            "max_latitude",
            "min_longitude",
            "max_longitude",
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_historical_backfill_slices_lookup", table_name="historical_backfill_slices")
    op.drop_table("historical_backfill_slices")
