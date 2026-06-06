"""add full AI analysis fields to signals and scenarios

Aligns the DB schema with the complete Claude crypto-parser output schema.

New columns on signals:
  language          — "en" | "fa" | "mixed"

New columns on scenarios:
  price_type        — "fixnumber" | "range"   (maps to schema `type` field)
  intents           — JSONB array of intent tags
  conditions        — JSONB array of activation conditions
  sentiment         — very_bullish/bullish/neutral/bearish/very_bearish/conditional
  urgency           — high | medium | low
  risk_level        — high | medium | low
  leverage          — float (leverage multiplier, null = not specified)
  ambiguity_score   — float 0.0–1.0
  possible_interpretations — JSONB array of alternative readings
  technical         — JSONB {indicators, patterns, divergences, key_levels}
  entities          — JSONB {exchanges, wallets, whale_amounts, events, news, people, projects}

Revision ID: f8a9b0c1d2e3
Revises: e7f8a9b0c1d2
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── signals ────────────────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE signals
        ADD COLUMN IF NOT EXISTS language VARCHAR(10)
    """)

    # ── scenarios ──────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS price_type VARCHAR(20)")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS intents JSONB DEFAULT '[]'")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS conditions JSONB DEFAULT '[]'")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS sentiment VARCHAR(20)")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS urgency VARCHAR(10)")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS risk_level VARCHAR(10)")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS leverage FLOAT")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS ambiguity_score FLOAT")
    op.execute("""
        ALTER TABLE scenarios
        ADD COLUMN IF NOT EXISTS possible_interpretations JSONB DEFAULT '[]'
    """)
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS technical JSONB")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS entities JSONB")

    # Back-fill price_type from the existing raw->>'type' field for all rows
    # that have raw data (won't fail if raw is NULL).
    op.execute("""
        UPDATE scenarios
        SET    price_type = raw->>'type'
        WHERE  raw IS NOT NULL
          AND  raw->>'type' IS NOT NULL
          AND  price_type IS NULL
    """)

    # Indexes for the most-likely-to-be-queried new columns
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_sentiment
        ON scenarios (sentiment)
        WHERE sentiment IS NOT NULL
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_intents_gin
        ON scenarios USING gin (intents)
        WHERE intents <> '[]'
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_signals_language
        ON signals (language)
        WHERE language IS NOT NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_signals_language")
    op.execute("DROP INDEX IF EXISTS ix_scenarios_intents_gin")
    op.execute("DROP INDEX IF EXISTS ix_scenarios_sentiment")

    for col in (
        "entities", "technical", "possible_interpretations",
        "ambiguity_score", "leverage", "risk_level",
        "urgency", "sentiment", "conditions", "intents", "price_type",
    ):
        op.execute(f"ALTER TABLE scenarios DROP COLUMN IF EXISTS {col}")

    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS language")
