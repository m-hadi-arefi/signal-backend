"""signal_engine_v2 — complete lifecycle tracking for signals and scenarios.

New columns:
  signals:         status, validation_error, completed_at
  scenarios:       timeframe, expire_at, updated_at, correction_applied
  scenario_results: hit_tp_index, exit_price, max_favorable, completed_at, data_gaps

New tables:
  scenario_events  — full audit trail for every state transition

Revision ID: a3b4c5d6e7f8
Revises: e6f7a8b9c0d1
Create Date: 2026-06-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # ── signals ────────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'validated'")
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS validation_error TEXT")
    op.execute("ALTER TABLE signals ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_signals_status
        ON signals (status)
        WHERE status NOT IN ('completed', 'invalid', 'rejected')
    """)

    # ── scenarios ──────────────────────────────────────────────────────────────
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS timeframe VARCHAR(10)")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS expire_at TIMESTAMP")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT NOW()")
    op.execute("ALTER TABLE scenarios ADD COLUMN IF NOT EXISTS correction_applied BOOLEAN DEFAULT FALSE")

    # Drop old partial index and replace with wider terminal-state guard
    op.execute("DROP INDEX IF EXISTS ix_scenarios_status_active")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_evaluable
        ON scenarios (id, signal_id, status)
        WHERE status IN ('running', 'active')
    """)

    # ── scenario_results ───────────────────────────────────────────────────────
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS hit_tp_index INTEGER")
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS exit_price FLOAT")
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS max_favorable FLOAT")
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP")
    op.execute("ALTER TABLE scenario_results ADD COLUMN IF NOT EXISTS data_gaps JSONB DEFAULT '[]'")

    # ── scenario_events ────────────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE IF NOT EXISTS scenario_events (
            id          BIGSERIAL    PRIMARY KEY,
            scenario_id INTEGER      NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
            event_type  VARCHAR(30)  NOT NULL,
            price       FLOAT,
            event_data  JSONB,
            occurred_at TIMESTAMP    NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenario_events_sc_ts
        ON scenario_events (scenario_id, occurred_at DESC)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenario_events_type
        ON scenario_events (event_type, occurred_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scenario_events")

    for col in ("data_gaps", "completed_at", "max_favorable", "exit_price", "hit_tp_index"):
        op.execute(f"ALTER TABLE scenario_results DROP COLUMN IF EXISTS {col}")

    for col in ("correction_applied", "updated_at", "expire_at", "timeframe"):
        op.execute(f"ALTER TABLE scenarios DROP COLUMN IF EXISTS {col}")

    op.execute("DROP INDEX IF EXISTS ix_scenarios_evaluable")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_scenarios_status_active
        ON scenarios (status, signal_id)
        WHERE status IN ('running', 'active')
    """)

    op.execute("DROP INDEX IF EXISTS ix_signals_status")
    for col in ("completed_at", "validation_error", "status"):
        op.execute(f"ALTER TABLE signals DROP COLUMN IF EXISTS {col}")
