"""signal pipeline v2: drop events, redesign signals → scenarios → scenario_results

Revision ID: f4a5b6c7d8e9
Revises: c1d2e3f4a5b6
Create Date: 2026-05-28 00:00:00.000000

Breaking changes:
  - events table dropped (raw event storage removed)
  - signals table completely redesigned (old columns gone)
  - signal_results and providers tables dropped
  - new: scenarios table (replaces inline signal fields)
  - new: scenario_results table (replaces signal_results)
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f4a5b6c7d8e9"
down_revision: Union[str, Sequence[str], None] = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # Remove old tables                                                    #
    # ------------------------------------------------------------------ #
    op.execute("DROP TABLE IF EXISTS events CASCADE")
    op.execute("DROP TABLE IF EXISTS signals CASCADE")
    op.execute("DROP TABLE IF EXISTS signal_results CASCADE")
    op.execute("DROP TABLE IF EXISTS providers CASCADE")

    # ------------------------------------------------------------------ #
    # signals                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        "signals",
        sa.Column("id",      sa.Integer(), nullable=False),
        sa.Column("symbol",  sa.String(length=20), nullable=False),
        sa.Column("trace_id", sa.String(length=36), nullable=False),

        # JSONB: {type, provider, channel?, url?, external_id?}
        sa.Column("source",  JSONB(), nullable=False),

        sa.Column("raw_text",    sa.Text(), nullable=True),
        sa.Column("ai_summary",  sa.Text(), nullable=True),

        # JSONB: {price, source, timestamp} — NULL when Redis had no data
        sa.Column("current_market_price", JSONB(), nullable=True),

        sa.Column("created_at",  sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.Column("analyzed_at", sa.DateTime(), nullable=True),

        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index("ix_signals_symbol",         "signals", ["symbol"])
    op.create_index("ix_signals_trace_id",        "signals", ["trace_id"])
    op.create_index("ix_signals_created_at",      "signals", ["created_at"])
    op.create_index("ix_signals_symbol_created",  "signals", ["symbol", "created_at"])
    # GIN index for JSONB source queries: WHERE source @> '{"provider":"x"}'
    op.create_index(
        "ix_signals_source_gin", "signals", ["source"],
        postgresql_using="gin",
    )

    # ------------------------------------------------------------------ #
    # scenarios                                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "scenarios",
        sa.Column("id",        sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.Integer(), nullable=False),

        sa.Column("direction",    sa.String(length=20),  nullable=True),
        sa.Column("entry_point",  sa.Float(),            nullable=True),
        sa.Column("entry_type",   sa.String(length=30),  nullable=True),
        sa.Column("take_profits", JSONB(),               nullable=True),
        sa.Column("stop_loss",    sa.Float(),            nullable=True),
        sa.Column("invalidation", sa.Text(),             nullable=True),
        sa.Column("confidence",   sa.Float(),            nullable=True),
        sa.Column("reasoning",    sa.Text(),             nullable=True),
        sa.Column("status",       sa.String(length=20),  nullable=False,
                  server_default=sa.text("'running'")),
        sa.Column("raw",          JSONB(),               nullable=True),

        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["signals.id"], ondelete="CASCADE"
        ),
    )

    op.create_index("ix_scenarios_signal_id", "scenarios", ["signal_id"])
    op.create_index("ix_scenarios_status",    "scenarios", ["status"])

    # ------------------------------------------------------------------ #
    # scenario_results                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        "scenario_results",
        sa.Column("id",          sa.Integer(), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=False),

        sa.Column("result",       sa.String(length=20), nullable=False),
        sa.Column("pnl_percent",  sa.Float(), nullable=True),
        sa.Column("hit_tp",       sa.Float(), nullable=True),
        sa.Column("hit_sl",       sa.Float(), nullable=True),
        sa.Column("max_drawdown", sa.Float(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(), nullable=True),

        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["scenarios.id"], ondelete="CASCADE"
        ),
    )

    op.create_index(
        "ix_scenario_results_scenario_id", "scenario_results", ["scenario_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_scenario_results_scenario_id", table_name="scenario_results")
    op.drop_table("scenario_results")

    op.drop_index("ix_scenarios_status",    table_name="scenarios")
    op.drop_index("ix_scenarios_signal_id", table_name="scenarios")
    op.drop_table("scenarios")

    op.drop_index("ix_signals_source_gin",       table_name="signals")
    op.drop_index("ix_signals_symbol_created",   table_name="signals")
    op.drop_index("ix_signals_created_at",       table_name="signals")
    op.drop_index("ix_signals_trace_id",         table_name="signals")
    op.drop_index("ix_signals_symbol",           table_name="signals")
    op.drop_table("signals")

    # Restore the previous signals schema so downgrade is clean
    op.create_table(
        "signals",
        sa.Column("id",           sa.Integer(), nullable=False),
        sa.Column("symbol",       sa.String(length=20), nullable=False),
        sa.Column("action",       sa.String(length=10), nullable=True),
        sa.Column("entry_price",  sa.Numeric(20, 8), nullable=True),
        sa.Column("target_price", sa.Numeric(20, 8), nullable=True),
        sa.Column("stop_loss",    sa.Numeric(20, 8), nullable=True),
        sa.Column("confidence",   sa.Float(), nullable=True),
        sa.Column("raw_signal",   JSONB(), nullable=False),
        sa.Column("trace_id",     sa.String(length=36), nullable=False),
        sa.Column("producer_type", sa.String(length=20), nullable=False),
        sa.Column("created_at",   sa.DateTime(), nullable=False,
                  server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])

    # Restore events table
    op.create_table(
        "events",
        sa.Column("id",       sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(), nullable=True),
        sa.Column("data",     sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_trace_id", "events", ["trace_id"], unique=True)
