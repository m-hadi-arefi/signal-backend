"""signal_tracking_active — per-scenario active flag, signal tracking columns, price extremes.

New columns:
  scenarios:        active (bool, replaces status='active' semantics)
  signals:          active (bool), active_scenarios_id (int FK), status default changed
  scenario_results: highest_price (float), lowest_price (float)

Data migration:
  scenarios: SET active=TRUE WHERE status='active', then reset those to status='running'
  signals:   SET active=TRUE, active_scenarios_id from active scenario WHERE exists

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-06-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a3b4c5d6e7f8"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── scenarios ──────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT FALSE")

    # Mark currently-active scenarios as active=TRUE before we reset their status
    op.execute("UPDATE scenarios SET active = TRUE WHERE status = 'active'")

    # Reset status back to 'running' — the active column is now the entered-state flag
    op.execute("UPDATE scenarios SET status = 'running' WHERE status = 'active'")

    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_active
        ON scenarios (signal_id, active)
        WHERE active = TRUE
    """)

    # ── signals ────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS active BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("""
        ALTER TABLE signals
        ADD COLUMN IF NOT EXISTS active_scenarios_id INTEGER
        REFERENCES scenarios(id) ON DELETE SET NULL
    """)

    # Populate from currently-active (now active=TRUE) scenarios
    op.execute("""
        UPDATE signals s
        SET    active = TRUE,
               active_scenarios_id = (
                   SELECT sc.id
                   FROM   scenarios sc
                   WHERE  sc.signal_id = s.id AND sc.active = TRUE
                   LIMIT  1
               ),
               status = 'running'
        WHERE  EXISTS (
            SELECT 1 FROM scenarios sc WHERE sc.signal_id = s.id AND sc.active = TRUE
        )
    """)

    # ── scenario_results ───────────────────────────────────────────────────────
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS highest_price FLOAT")
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS lowest_price FLOAT")

    # Backfill from entry_price + max_favorable/max_drawdown for long scenarios
    op.execute("""
        UPDATE scenario_results sr
        SET    highest_price = CASE
                   WHEN sc.direction = 'long'  AND sr.max_favorable IS NOT NULL
                       THEN sr.entry_price * (1 + sr.max_favorable / 100)
                   WHEN sc.direction = 'short' AND sr.max_drawdown  IS NOT NULL
                       THEN sr.entry_price * (1 - sr.max_drawdown  / 100)
                   ELSE sr.entry_price
               END,
               lowest_price  = CASE
                   WHEN sc.direction = 'long'  AND sr.max_drawdown  IS NOT NULL
                       THEN sr.entry_price * (1 + sr.max_drawdown  / 100)
                   WHEN sc.direction = 'short' AND sr.max_favorable IS NOT NULL
                       THEN sr.entry_price * (1 - sr.max_favorable / 100)
                   ELSE sr.entry_price
               END
        FROM   scenarios sc
        WHERE  sr.scenario_id = sc.id
          AND  sr.entry_price IS NOT NULL AND sr.entry_price > 0
    """)


def downgrade() -> None:
    for col in ("lowest_price", "highest_price"):
        op.execute(f"ALTER TABLE scenario_results DROP COLUMN IF EXISTS {col}")

    op.execute("DROP INDEX IF EXISTS ix_scenarios_active")
    op.execute("ALTER TABLE scenarios DROP COLUMN IF EXISTS active")

    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS active_scenarios_id")
    op.execute("ALTER TABLE signals DROP COLUMN IF EXISTS active")
