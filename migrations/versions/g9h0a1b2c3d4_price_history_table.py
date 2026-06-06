"""Replace scenario_results.price_history JSONB with scenario_price_points table.

Why:
  The JSONB blob approach had two problems:
  1. The entire array is rewritten on every evaluator cycle (expensive for long signals).
  2. Individual points are not queryable — you can't filter/aggregate over them.

What this migration does:
  1. Creates scenario_price_points table (id, scenario_id, recorded_at, price, pnl_percent).
  2. Migrates every point in existing price_history blobs into the new table.
  3. Drops the price_history column from scenario_results.

Revision ID: g9h0a1b2c3d4
Revises: f8a9b0c1d2e3
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "g9h0a1b2c3d4"
down_revision: Union[str, Sequence[str], None] = "f8a9b0c1d2e3"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── 1. Create the new table ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS scenario_price_points (
            id          BIGSERIAL PRIMARY KEY,
            scenario_id INTEGER   NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
            recorded_at TIMESTAMP NOT NULL,
            price       FLOAT     NOT NULL,
            pnl_percent FLOAT,
            UNIQUE (scenario_id, recorded_at)
        )
    """)

    # Primary access pattern: fetch all points for a scenario ordered by time.
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenario_pp_sc_ts
        ON scenario_price_points (scenario_id, recorded_at ASC)
    """)

    # ── 2. Migrate existing JSONB data ─────────────────────────────────────────
    # Each element in price_history looks like {"ts": "2026-06-01T10:00:00", "price": 65000}
    # We cast the ts string to TIMESTAMP and insert one row per point.
    op.execute("""
        INSERT INTO scenario_price_points (scenario_id, recorded_at, price)
        SELECT
            sr.scenario_id,
            (point->>'ts')::TIMESTAMP   AS recorded_at,
            (point->>'price')::FLOAT    AS price
        FROM   scenario_results sr,
               LATERAL jsonb_array_elements(
                   COALESCE(sr.price_history, '[]'::jsonb)
               ) AS point
        WHERE  sr.price_history IS NOT NULL
          AND  sr.price_history <> '[]'::jsonb
          AND  (point->>'ts')   IS NOT NULL
          AND  (point->>'price') IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # ── 3. Drop the old column ─────────────────────────────────────────────────
    op.execute("ALTER TABLE scenario_results DROP COLUMN IF EXISTS price_history")


def downgrade() -> None:
    # Restore the column with an empty default (data loss — points are gone).
    op.execute("""
        ALTER TABLE scenario_results
        ADD COLUMN IF NOT EXISTS price_history JSONB NOT NULL DEFAULT '[]'
    """)

    op.execute("DROP TABLE IF EXISTS scenario_price_points")
