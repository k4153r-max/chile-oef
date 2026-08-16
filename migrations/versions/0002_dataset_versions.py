"""immutable dataset versions

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "ingestion_run_id",
            sa.Uuid(),
            sa.ForeignKey("ingestion_runs.id"),
            nullable=False,
        ),
        sa.Column(
            "raw_artifact_id",
            sa.Uuid(),
            sa.ForeignKey("raw_artifacts.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("ingestion_run_id", "raw_artifact_id"),
    )
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("dataset_id", sa.String(128), nullable=False),
        sa.Column("version", sa.String(128), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("manifest_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_json", postgresql.JSONB(), nullable=False),
        sa.Column("git_commit", sa.String(64)),
        sa.UniqueConstraint("dataset_id", "version"),
        sa.UniqueConstraint("manifest_sha256"),
    )
    op.create_table(
        "dataset_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "raw_artifact_id",
            sa.Uuid(),
            sa.ForeignKey("raw_artifacts.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("dataset_version_id", "raw_artifact_id"),
    )
    op.create_table(
        "dataset_event_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "dataset_version_id",
            sa.Uuid(),
            sa.ForeignKey("dataset_versions.id"),
            nullable=False,
        ),
        sa.Column(
            "event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.UniqueConstraint("dataset_version_id", "event_revision_id"),
    )


def downgrade() -> None:
    op.drop_table("dataset_event_revisions")
    op.drop_table("dataset_artifacts")
    op.drop_table("dataset_versions")
    op.drop_table("ingestion_artifacts")
