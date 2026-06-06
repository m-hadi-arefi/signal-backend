"""create events

Revision ID: f38045b5c7d9
Revises: 3a4f295c3c5e
Create Date: 2026-05-11 10:30:01.615935
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

revision: str = 'f38045b5c7d9'
down_revision: Union[str, Sequence[str], None] = '3a4f295c3c5e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    existing = set(sa_inspect(op.get_bind()).get_table_names())
    if 'events' not in existing:
        op.create_table(
            'events',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('trace_id', sa.String(), nullable=True),
            sa.Column('data', sa.JSON(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_events_trace_id'), 'events', ['trace_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_events_trace_id'), table_name='events')
    op.drop_table('events')
