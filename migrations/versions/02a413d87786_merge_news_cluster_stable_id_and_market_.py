"""merge news_cluster stable_id and market heads

Revision ID: 02a413d87786
Revises: daa4a59f33dc, 6f6d98640ef9
Create Date: 2026-06-22 11:55:48.520183

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '02a413d87786'
down_revision: Union[str, Sequence[str], None] = ('daa4a59f33dc', '6f6d98640ef9')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
