"""init

Revision ID: fc4ca71b7078
Revises: f38045b5c7d9
Create Date: 2026-05-16 13:30:02.241439

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fc4ca71b7078'
down_revision: Union[str, Sequence[str], None] = 'f38045b5c7d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
