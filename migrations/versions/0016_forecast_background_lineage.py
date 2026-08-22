"""Add adaptive background-rate lineage to forecasts and evaluations.

Revision ID: 0016
Revises: 0015
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "forecast_runs",
        sa.Column("background_rate_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_forecast_runs_background_rate_run_id",
        "forecast_runs",
        "seismicity_background_rate_runs",
        ["background_rate_run_id"],
        ["id"],
    )
    op.add_column(
        "evaluation_runs",
        sa.Column("background_rate_run_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_evaluation_runs_background_rate_run_id",
        "evaluation_runs",
        "seismicity_background_rate_runs",
        ["background_rate_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_evaluation_runs_background_rate_run_id",
        "evaluation_runs",
        type_="foreignkey",
    )
    op.drop_column("evaluation_runs", "background_rate_run_id")
    op.drop_constraint(
        "fk_forecast_runs_background_rate_run_id",
        "forecast_runs",
        type_="foreignkey",
    )
    op.drop_column("forecast_runs", "background_rate_run_id")
