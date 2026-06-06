"""add performance indexes for evaluator and API queries

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-06-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Evaluator's main loop: WHERE status NOT IN ('success','failed','expired')
    # Partial index covers only the hot set (running + active rows).
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_status_active
        ON scenarios (status, signal_id)
        WHERE status IN ('running', 'active')
    """)

    # scenario_results lookup by scenario_id: covered by unique constraint,
    # but an explicit index on (scenario_id, result) helps the evaluator's
    # "skip already-terminal" guard.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenario_results_result
        ON scenario_results (result)
        WHERE result IN ('running')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scenarios_status_active")
    op.execute("DROP INDEX IF EXISTS ix_scenario_results_result")
