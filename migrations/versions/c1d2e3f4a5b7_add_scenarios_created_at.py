"""add created_at column to scenarios table

Revision ID: c1d2e3f4a5b7
Revises: a3b4c5d6e7f8
Create Date: 2026-06-04
"""
from typing import Sequence, Union
from alembic import op

revision: str = "c1d2e3f4a5b7"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE scenarios
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP NOT NULL DEFAULT NOW()
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS created_at")
