"""merge collector and main heads

Revision ID: e89f78e7e898
Revises: 02a413d87786, e8f1a2b3c4d5
Create Date: 2026-06-22 12:09:52.407688

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e89f78e7e898'
down_revision: Union[str, Sequence[str], None] = ('02a413d87786', 'e8f1a2b3c4d5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
