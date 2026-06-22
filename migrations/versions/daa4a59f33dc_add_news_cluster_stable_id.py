"""add news_cluster stable_id

Revision ID: daa4a59f33dc
Revises: 211e9d09101d
Create Date: 2026-06-22 10:13:48.758219

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'daa4a59f33dc'
# news_cluster.stable_id는 마켓 마이그레이션과 독립적이므로 커밋된 head(211e9d09101d)에 직접 연결.
down_revision: Union[str, Sequence[str], None] = '211e9d09101d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # cluster id 승계용 안정 식별자 컬럼 추가만 수행한다.
    # ⚠️ autogenerate가 잡은 news_analysis·issue_docent DROP은 제거했다 — 두 테이블은 분석단계
    # (06/07) 소관으로 이 repo ORM 밖에 있을 뿐 실재하는 테이블이라 삭제하면 안 된다.
    op.add_column('news_cluster', sa.Column('stable_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('news_cluster', 'stable_id')
