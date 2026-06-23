"""merge global index markets and dictionary quiz heads

Revision ID: bef094fbc038
Revises: c4e6f8a0b2d3, c4e8b1a9f2d6
Create Date: 2026-06-23 10:49:29.978464

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bef094fbc038'
down_revision: Union[str, Sequence[str], None] = ('c4e6f8a0b2d3', 'c4e8b1a9f2d6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
