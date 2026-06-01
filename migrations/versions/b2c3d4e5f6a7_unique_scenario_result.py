"""add unique constraint + entered_at column to scenario_results

Adds:
  - entered_at (DateTime, nullable): timestamp when the scenario's entry
    condition was first confirmed. NULL means "waiting for entry".
  - UNIQUE(scenario_id): enables efficient ON CONFLICT upsert so the
    evaluator can write a fresh snapshot every 60 seconds.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-31 00:00:00.000000
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scenario_results",
        sa.Column("entered_at", sa.DateTime(), nullable=True),
    )

    # Remove duplicates before adding unique constraint.
    # Keep the most recent row per scenario (by evaluated_at, then id).
    op.execute("""
        DELETE FROM scenario_results
        WHERE id NOT IN (
            SELECT DISTINCT ON (scenario_id) id
            FROM scenario_results
            ORDER BY scenario_id, evaluated_at DESC NULLS LAST, id DESC
        )
    """)

    op.create_unique_constraint(
        "uq_scenario_results_scenario_id",
        "scenario_results",
        ["scenario_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_scenario_results_scenario_id",
        "scenario_results",
        type_="unique",
    )
    op.drop_column("scenario_results", "entered_at")
