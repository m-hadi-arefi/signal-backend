"""add props JSONB to signals and scenarios

Adds an extensible `props` field to both tables so that extra metadata
(new AI fields, frontend hints, debug data) can be stored without altering
the main schema columns or breaking downstream services.

Pattern:
  - Consumers that don't care about extra fields just ignore props.
  - New data fields can be stashed in props until they're stable enough
    to get their own column.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "d6e7f8a9b0c1"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE signals
        ADD COLUMN IF NOT EXISTS props JSONB NOT NULL DEFAULT '{}'
    """)
    op.execute("""
        ALTER TABLE scenarios
        ADD COLUMN IF NOT EXISTS props JSONB NOT NULL DEFAULT '{}'
    """)
    # GIN index lets you query props like: WHERE props @> '{"key": "value"}'
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_signals_props_gin
        ON signals USING gin (props)
        WHERE props <> '{}'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_props_gin
        ON scenarios USING gin (props)
        WHERE props <> '{}'
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_scenarios_props_gin")
    op.execute("DROP INDEX IF EXISTS ix_signals_props_gin")
    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS props")
    op.execute("ALTER TABLE signals   DROP COLUMN IF EXISTS props")
