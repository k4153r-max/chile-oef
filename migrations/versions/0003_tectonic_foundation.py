"""tectonic assets, slab, faults, grid, and classifications

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import geoalchemy2
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tectonic_releases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("source_id", sa.String(64), sa.ForeignKey("catalog_sources.id"), nullable=False),
        sa.Column("release_id", sa.String(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("doi", sa.Text()),
        sa.Column("license_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "release_id"),
    )
    op.create_table(
        "tectonic_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("tectonic_releases.id"),
            nullable=False,
        ),
        sa.Column(
            "raw_artifact_id",
            sa.Uuid(),
            sa.ForeignKey("raw_artifacts.id"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer()),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", "asset_type"),
    )
    op.create_table(
        "slab_nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("tectonic_releases.id"),
            nullable=False,
        ),
        sa.Column("longitude_index", sa.Integer(), nullable=False),
        sa.Column("latitude_index", sa.Integer(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("depth_km", sa.Float(), nullable=False),
        sa.Column("dip_degrees", sa.Float()),
        sa.Column("strike_degrees", sa.Float()),
        sa.Column("thickness_km", sa.Float()),
        sa.Column("uncertainty_km", sa.Float()),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.UniqueConstraint("release_id", "longitude_index", "latitude_index"),
    )
    op.create_index(
        "ix_slab_nodes_geometry_gist",
        "slab_nodes",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index(
        "ix_slab_nodes_release_grid",
        "slab_nodes",
        ["release_id", "longitude_index", "latitude_index"],
    )
    op.create_table(
        "fault_traces",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "release_id",
            sa.Uuid(),
            sa.ForeignKey("tectonic_releases.id"),
            nullable=False,
        ),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("fault_system", sa.String(128)),
        sa.Column("fault_name", sa.Text()),
        sa.Column("trace_name", sa.Text()),
        sa.Column("trace_type", sa.String(64)),
        sa.Column("activity_class", sa.String(64)),
        sa.Column("strike_degrees", sa.Float()),
        sa.Column("dip_degrees", sa.Float()),
        sa.Column("rake_degrees", sa.Float()),
        sa.Column("length_km", sa.Float()),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="MULTILINESTRING", srid=4326),
            nullable=False,
        ),
        sa.Column("properties_json", postgresql.JSONB(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("release_id", "external_id"),
    )
    op.create_index(
        "ix_fault_traces_geometry_gist",
        "fault_traces",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_table(
        "spatial_grids",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("resolution_degrees", sa.Float(), nullable=False),
        sa.Column("min_latitude", sa.Float(), nullable=False),
        sa.Column("max_latitude", sa.Float(), nullable=False),
        sa.Column("min_longitude", sa.Float(), nullable=False),
        sa.Column("max_longitude", sa.Float(), nullable=False),
        sa.Column("crs", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("definition_sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(), nullable=False),
    )
    op.create_table(
        "seismic_cells",
        sa.Column("id", sa.String(180), primary_key=True),
        sa.Column("grid_id", sa.String(128), sa.ForeignKey("spatial_grids.id"), nullable=False),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("column_index", sa.Integer(), nullable=False),
        sa.Column("center_latitude", sa.Float(), nullable=False),
        sa.Column("center_longitude", sa.Float(), nullable=False),
        sa.Column("area_km2", sa.Float(), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="POLYGON", srid=4326),
            nullable=False,
        ),
        sa.UniqueConstraint("grid_id", "row_index", "column_index"),
    )
    op.create_index(
        "ix_seismic_cells_geometry_gist",
        "seismic_cells",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_table(
        "event_tectonic_classifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "event_revision_id",
            sa.Uuid(),
            sa.ForeignKey("event_revisions.id"),
            nullable=False,
        ),
        sa.Column(
            "slab_release_id",
            sa.Uuid(),
            sa.ForeignKey("tectonic_releases.id"),
            nullable=False,
        ),
        sa.Column("fault_release_id", sa.Uuid(), sa.ForeignKey("tectonic_releases.id")),
        sa.Column("method_version", sa.String(64), nullable=False),
        sa.Column("calibration_status", sa.String(64), nullable=False),
        sa.Column("label", sa.String(32), nullable=False),
        sa.Column("max_probability", sa.Float(), nullable=False),
        sa.Column("slab_depth_km", sa.Float()),
        sa.Column("signed_vertical_residual_km", sa.Float()),
        sa.Column("signed_normal_distance_km", sa.Float()),
        sa.Column("horizontal_fault_distance_km", sa.Float()),
        sa.Column("probabilities_json", postgresql.JSONB(), nullable=False),
        sa.Column("diagnostics_json", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "max_probability >= 0 AND max_probability <= 1",
            name="max_probability_range",
        ),
        sa.UniqueConstraint(
            "event_revision_id",
            "slab_release_id",
            "fault_release_id",
            "method_version",
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_index(
        "ix_event_tectonic_classifications_label",
        "event_tectonic_classifications",
        ["label"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_tectonic_classifications_label",
        table_name="event_tectonic_classifications",
    )
    op.drop_table("event_tectonic_classifications")
    op.drop_index("ix_seismic_cells_geometry_gist", table_name="seismic_cells")
    op.drop_table("seismic_cells")
    op.drop_table("spatial_grids")
    op.drop_index("ix_fault_traces_geometry_gist", table_name="fault_traces")
    op.drop_table("fault_traces")
    op.drop_index("ix_slab_nodes_release_grid", table_name="slab_nodes")
    op.drop_index("ix_slab_nodes_geometry_gist", table_name="slab_nodes")
    op.drop_table("slab_nodes")
    op.drop_table("tectonic_assets")
    op.drop_table("tectonic_releases")
