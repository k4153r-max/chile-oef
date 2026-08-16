"""nearest-neighbor declustering runs and event classifications

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seismicity_declustering_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "gutenberg_richter_estimate_id",
            sa.Uuid(),
            sa.ForeignKey("gutenberg_richter_estimates.id"),
            nullable=False,
        ),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("min_latitude", sa.Float()),
        sa.Column("max_latitude", sa.Float()),
        sa.Column("min_longitude", sa.Float()),
        sa.Column("max_longitude", sa.Float()),
        sa.Column("magnitude_type", sa.String(16), nullable=False),
        sa.Column("minimum_magnitude", sa.Float(), nullable=False),
        sa.Column("b_value_used", sa.Float(), nullable=False),
        sa.Column("fractal_dimension", sa.Float(), nullable=False),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("classified_event_count", sa.Integer(), nullable=False),
        sa.Column("background_event_count", sa.Integer(), nullable=False),
        sa.Column("log_eta_threshold", sa.Float()),
        sa.Column("catalog_as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("event_count >= 0", name="event_count_non_negative"),
    )
    op.create_table(
        "event_declustering_classifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "declustering_run_id",
            sa.Uuid(),
            sa.ForeignKey("seismicity_declustering_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "parent_event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
        ),
        sa.Column("log10_eta", sa.Float()),
        sa.Column("is_background", sa.Boolean()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_event_declustering_classifications_run",
        "event_declustering_classifications",
        ["declustering_run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_declustering_classifications_run",
        table_name="event_declustering_classifications",
    )
    op.drop_table("event_declustering_classifications")
    op.drop_table("seismicity_declustering_runs")
