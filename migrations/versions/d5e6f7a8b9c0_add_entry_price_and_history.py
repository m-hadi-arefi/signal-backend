"""add entry_price and price_history to scenario_results

Revision ID: d5e6f7a8b9c0
Revises: b2c3d4e5f6a7
Create Date: 2026-06-02 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE scenario_results
        ADD COLUMN IF NOT EXISTS entry_price FLOAT
    """)
    op.execute("""
        ALTER TABLE scenario_results
        ADD COLUMN IF NOT EXISTS price_history JSONB NOT NULL DEFAULT '[]'::jsonb
    """)


def downgrade() -> None:
    op.drop_column("scenario_results", "price_history")
    op.drop_column("scenario_results", "entry_price")
