"""add admin tables: pipeline_logs, http_api_sources, scraper_sources

Revision ID: b3e9f1a2d4c5
Revises: fc4ca71b7078
Create Date: 2026-05-26 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB

revision: str = 'b3e9f1a2d4c5'
down_revision: Union[str, Sequence[str], None] = 'fc4ca71b7078'
branch_labels = None
depends_on = None


def upgrade() -> None:
    existing = set(sa_inspect(op.get_bind()).get_table_names())

    if 'pipeline_logs' not in existing:
        op.create_table(
            'pipeline_logs',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('trace_id', sa.String(length=36), nullable=False),
            sa.Column('event_type', sa.String(length=50)),
            sa.Column('source_name', sa.String(length=255)),
            sa.Column('service', sa.String(length=50)),
            sa.Column('step', sa.String(length=50)),
            sa.Column('status', sa.String(length=20), nullable=False),
            sa.Column('ai_signals', JSONB),
            sa.Column('error_message', sa.Text()),
            sa.Column('created_at', sa.DateTime()),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_pipeline_logs_trace_id',       'pipeline_logs', ['trace_id'])
        op.create_index('ix_pipeline_logs_created_at',     'pipeline_logs', ['created_at'])
        op.create_index('ix_pipeline_logs_trace_service',  'pipeline_logs', ['trace_id', 'service'])
        op.create_index('ix_pipeline_logs_status_created', 'pipeline_logs', ['status', 'created_at'])

    if 'http_api_sources' not in existing:
        op.create_table(
            'http_api_sources',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('url', sa.Text(), nullable=False),
            sa.Column('data_path', sa.String(length=255)),
            sa.Column('id_field', sa.String(length=255)),
            sa.Column('text_field', sa.String(length=255)),
            sa.Column('eval_str', sa.Text()),
            sa.Column('auth_type', sa.String(length=20)),
            sa.Column('auth_key', sa.String(length=255)),
            sa.Column('auth_value', sa.String(length=500)),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime()),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
        )

    if 'scraper_sources' not in existing:
        op.create_table(
            'scraper_sources',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('rss', sa.Text()),
            sa.Column('filter_tag', sa.String(length=100)),
            sa.Column('filter_value', sa.String(length=500)),
            sa.Column('listing_url', sa.Text()),
            sa.Column('base_url', sa.Text()),
            sa.Column('box_selector', sa.Text()),
            sa.Column('post_selector', sa.Text()),
            sa.Column('is_ssr', sa.Boolean(), server_default='false'),
            sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
            sa.Column('created_at', sa.DateTime()),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('name'),
        )

    # Seeds are idempotent (ON CONFLICT DO NOTHING)
    op.execute("""
        INSERT INTO http_api_sources
            (name, url, data_path, id_field, eval_str, is_active, created_at)
        VALUES (
            'Binance Square Signals',
            'https://www.binance.com/bapi/composite/v4/friendly/pgc/content/queryByHashtag?hashtag=%23signals&pageIndex=1&pageSize=20&orderBy=LATEST',
            'data.feedData',
            'id',
            'lambda item: f"[{item[''authorName'']}] {item[''content'']}"',
            true,
            NOW()
        )
        ON CONFLICT (name) DO NOTHING
    """)

    op.execute("""
        INSERT INTO scraper_sources (name, listing_url, base_url, post_selector, is_active, created_at)
        VALUES ('CoinTelegraph Markets', 'https://cointelegraph.com/category/markets',
                'https://cointelegraph.com', 'a[href^="/markets/"]', true, NOW())
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO scraper_sources (name, rss, filter_tag, filter_value, is_active, created_at)
        VALUES ('CoinDesk Markets', 'https://www.coindesk.com/arc/outboundfeeds/rss/',
                'category', '^Markets$', true, NOW())
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO scraper_sources (name, rss, filter_tag, filter_value, is_active, created_at)
        VALUES ('Bitcoin Magazine Markets', 'https://bitcoinmagazine.com/feed',
                'category', '^MARKETS$', true, NOW())
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO scraper_sources (name, listing_url, base_url, box_selector, post_selector, is_active, created_at)
        VALUES ('U.Today Market Review', 'https://u.today/crypto-market-review',
                'https://u.today', 'div.news__item', 'a.news__item-body', true, NOW())
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO scraper_sources (name, rss, is_active, created_at)
        VALUES ('AMBCrypto Analysis', 'https://ambcrypto.com/category/analysis/feed/', true, NOW())
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO scraper_sources (name, rss, is_active, created_at)
        VALUES ('Nobitex Mag تحلیل‌ها', 'https://nobitex.ir/mag/category/analysis/feed/', true, NOW())
        ON CONFLICT (name) DO NOTHING
    """)


def downgrade() -> None:
    op.drop_table('scraper_sources')
    op.drop_table('http_api_sources')
    op.drop_index('ix_pipeline_logs_status_created', 'pipeline_logs')
    op.drop_index('ix_pipeline_logs_trace_service',  'pipeline_logs')
    op.drop_index('ix_pipeline_logs_created_at',     'pipeline_logs')
    op.drop_index('ix_pipeline_logs_trace_id',       'pipeline_logs')
    op.drop_table('pipeline_logs')
