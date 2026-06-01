"""make news.published_at nullable

Revision ID: 9f554fce279d
Revises: bac51ac9aec1
Create Date: 2026-06-01 15:29:12.820097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9f554fce279d'
down_revision: Union[str, Sequence[str], None] = 'bac51ac9aec1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("news", "published_at", existing_type=sa.DateTime(timezone=True), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # NOT NULL 복구 전, nullable 동안 쌓인 NULL 행을 먼저 제거 (없으면 ALTER가 실패)
    op.execute("DELETE FROM news WHERE published_at IS NULL")
    op.alter_column("news", "published_at", existing_type=sa.DateTime(timezone=True), nullable=False)
