"""add news.is_duplicate (임베딩 유사도 근접 중복 soft flag)

임베딩 유사도(cosine ≥ 0.95) 근접 중복을 하드 삭제 대신 soft flag로 표시하기 위한
컬럼(→ 설계 05 §4.2). 행을 보존해 news_cluster FK 정합성·URL 멱등 재수집 방지·추적성을
지킨다. 클러스터링·분석은 is_duplicate=false만 읽는다.

Revision ID: b2d4f6a8c1e3
Revises: e91033167c44
Create Date: 2026-06-09 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d4f6a8c1e3'
down_revision: Union[str, Sequence[str], None] = 'e91033167c44'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 기존 행은 server_default('false')로 채워져 NOT NULL을 만족한다.
    op.add_column(
        'news',
        sa.Column('is_duplicate', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('news', 'is_duplicate')
