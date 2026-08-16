"""catalog foundation

Revision ID: 0001
Revises: None
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "catalog_sources",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("authority", sa.String(255), nullable=False),
        sa.Column("role", sa.String(64), nullable=False),
        sa.Column("license_id", sa.String(128)),
        sa.Column("attribution", sa.Text()),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_endpoints",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "kind", "url"),
    )
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("request_url", sa.Text(), nullable=False),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("revisions_inserted", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
    )
    op.create_table(
        "raw_artifacts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_length", sa.BigInteger(), nullable=False),
        sa.Column("media_type", sa.String(255)),
        sa.Column("http_status", sa.Integer()),
        sa.Column("response_headers", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint("source_id", "sha256"),
    )
    op.create_table(
        "source_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("source_event_id", sa.String(255), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "source_event_id"),
    )
    op.create_table(
        "event_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_event_id", sa.Uuid(), sa.ForeignKey("source_events.id"), nullable=False),
        sa.Column("raw_artifact_id", sa.Uuid(), sa.ForeignKey("raw_artifacts.id"), nullable=False),
        sa.Column("revision_hash", sa.String(64), nullable=False),
        sa.Column("event_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("depth_km", sa.Float()),
        sa.Column("magnitude", sa.Float()),
        sa.Column("magnitude_type", sa.String(32)),
        sa.Column("place", sa.Text()),
        sa.Column("status", sa.String(32)),
        sa.Column("location_uncertainty_km", sa.Float()),
        sa.Column("depth_uncertainty_km", sa.Float()),
        sa.Column("magnitude_uncertainty", sa.Float()),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column("parsed_payload", postgresql.JSONB(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="latitude_range"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="longitude_range"),
        sa.UniqueConstraint("source_event_id", "revision_hash"),
    )
    op.create_index("ix_event_revisions_event_time", "event_revisions", ["event_time"])
    op.create_index("ix_event_revisions_available_at", "event_revisions", ["available_at"])
    op.create_index(
        "ix_event_revisions_geometry_gist",
        "event_revisions",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_table(
        "data_quality_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.Column("flag", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("event_revision_id", "flag"),
    )
    op.create_table(
        "canonical_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "canonical_event_memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "canonical_event_id",
            sa.Uuid(),
            sa.ForeignKey("canonical_events.id"),
            nullable=False,
        ),
        sa.Column("source_event_id", sa.Uuid(), sa.ForeignKey("source_events.id"), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("match_probability", sa.Float(), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("canonical_event_id", "source_event_id", "valid_from"),
    )
    op.create_table(
        "deduplication_candidates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "left_event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "right_event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("match_probability", sa.Float(), nullable=False),
        sa.Column("time_delta_seconds", sa.Float(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("magnitude_delta", sa.Float()),
        sa.Column("depth_delta_km", sa.Float()),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("match_probability >= 0 AND match_probability <= 1", name="probability"),
        sa.UniqueConstraint("left_event_revision_id", "right_event_revision_id", "method_version"),
    )


def downgrade() -> None:
    op.drop_table("deduplication_candidates")
    op.drop_table("canonical_event_memberships")
    op.drop_table("canonical_events")
    op.drop_table("data_quality_logs")
    op.drop_index("ix_event_revisions_geometry_gist", table_name="event_revisions")
    op.drop_index("ix_event_revisions_available_at", table_name="event_revisions")
    op.drop_index("ix_event_revisions_event_time", table_name="event_revisions")
    op.drop_table("event_revisions")
    op.drop_table("source_events")
    op.drop_table("raw_artifacts")
    op.drop_table("ingestion_runs")
    op.drop_table("source_endpoints")
    op.drop_table("catalog_sources")
