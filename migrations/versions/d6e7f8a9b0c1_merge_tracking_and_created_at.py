"""merge: signal_tracking_active + add_scenarios_created_at

Revision ID: d6e7f8a9b0c1
Revises: b5c6d7e8f9a0, c1d2e3f4a5b7
Create Date: 2026-06-04
"""
from typing import Sequence, Union

revision: str = "d6e7f8a9b0c1"
down_revision: Union[str, Sequence[str], None] = ("b5c6d7e8f9a0", "c1d2e3f4a5b7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
