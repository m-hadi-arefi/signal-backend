"""add unique constraint + entered_at column to scenario_results

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
    # ADD COLUMN IF NOT EXISTS — safe to re-run
    op.execute("""
        ALTER TABLE scenario_results
        ADD COLUMN IF NOT EXISTS entered_at TIMESTAMP
    """)

    # Remove duplicate rows before adding unique constraint (keeps latest per scenario)
    op.execute("""
        DELETE FROM scenario_results
        WHERE id NOT IN (
            SELECT DISTINCT ON (scenario_id) id
            FROM scenario_results
            ORDER BY scenario_id, evaluated_at DESC NULLS LAST, id DESC
        )
    """)

    # Add unique constraint only if it doesn't already exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_scenario_results_scenario_id'
            ) THEN
                ALTER TABLE scenario_results
                ADD CONSTRAINT uq_scenario_results_scenario_id UNIQUE (scenario_id);
            END IF;
        END$$
    """)


def downgrade() -> None:
    op.drop_constraint(
        "uq_scenario_results_scenario_id",
        "scenario_results",
        type_="unique",
    )
    op.drop_column("scenario_results", "entered_at")
