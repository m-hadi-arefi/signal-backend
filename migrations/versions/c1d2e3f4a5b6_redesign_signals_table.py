"""redesign signals table with full provenance and AI field mapping

Revision ID: c1d2e3f4a5b6
Revises: b3e9f1a2d4c5
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b3e9f1a2d4c5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop old signals table — was never populated, safe to recreate clean
    op.execute("DROP TABLE IF EXISTS signals CASCADE")

    op.create_table(
        'signals',
        sa.Column('id', sa.Integer(), nullable=False),

        # Core signal fields
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('action', sa.String(length=10), nullable=True),
        sa.Column('entry_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('target_price', sa.Numeric(20, 8), nullable=True),
        sa.Column('stop_loss', sa.Numeric(20, 8), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('ambiguity_score', sa.Float(), nullable=True),
        sa.Column('leverage', sa.Float(), nullable=True),
        sa.Column('timeframe', sa.String(length=20), nullable=True),
        sa.Column('sentiment', sa.String(length=20), nullable=True),
        sa.Column('urgency', sa.String(length=10), nullable=True),
        sa.Column('risk_level', sa.String(length=10), nullable=True),
        sa.Column('reasoning', sa.Text(), nullable=True),
        sa.Column('intents', JSONB(), nullable=True),
        sa.Column('raw_signal', JSONB(), nullable=False),

        # Provenance
        sa.Column('trace_id', sa.String(length=36), nullable=False),
        sa.Column('producer_type', sa.String(length=20), nullable=False),
        sa.Column('source_name', sa.String(length=255), nullable=True),
        sa.Column('event_type', sa.String(length=50), nullable=True),

        # Telegram-specific
        sa.Column('channel_id', sa.BigInteger(), nullable=True),
        sa.Column('channel_name', sa.String(length=255), nullable=True),
        sa.Column('message_id', sa.BigInteger(), nullable=True),

        # Web-source-specific
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('item_id', sa.String(length=255), nullable=True),
        sa.Column('source_published_at', sa.DateTime(), nullable=True),

        sa.Column('created_at', sa.DateTime(), nullable=False,
                  server_default=sa.text('NOW()')),

        sa.PrimaryKeyConstraint('id'),
    )

    op.create_index('ix_signals_symbol', 'signals', ['symbol'])
    op.create_index('ix_signals_trace_id', 'signals', ['trace_id'])
    op.create_index('ix_signals_producer_type', 'signals', ['producer_type'])
    op.create_index('ix_signals_source_name', 'signals', ['source_name'])
    op.create_index('ix_signals_channel_id', 'signals', ['channel_id'])
    op.create_index('ix_signals_created_at', 'signals', ['created_at'])
    op.create_index('ix_signals_symbol_created', 'signals', ['symbol', 'created_at'])
    op.create_index('ix_signals_producer_source', 'signals', ['producer_type', 'source_name'])
    op.create_index(
        'ix_signals_raw_signal_gin', 'signals', ['raw_signal'],
        postgresql_using='gin'
    )


def downgrade() -> None:
    op.drop_index('ix_signals_raw_signal_gin', table_name='signals')
    op.drop_index('ix_signals_producer_source', table_name='signals')
    op.drop_index('ix_signals_symbol_created', table_name='signals')
    op.drop_index('ix_signals_created_at', table_name='signals')
    op.drop_index('ix_signals_channel_id', table_name='signals')
    op.drop_index('ix_signals_source_name', table_name='signals')
    op.drop_index('ix_signals_producer_type', table_name='signals')
    op.drop_index('ix_signals_trace_id', table_name='signals')
    op.drop_index('ix_signals_symbol', table_name='signals')
    op.drop_table('signals')

    # Restore minimal old table so downgrade is complete
    op.create_table(
        'signals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(), nullable=True),
        sa.Column('type', sa.String(), nullable=True),
        sa.Column('price', sa.Float(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('raw_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_signals_symbol', 'signals', ['symbol'])
