"""drop news.preprocessed_at (인메모리 전처리 전환으로 미사용)

전처리가 수집→전처리→1회 저장(인메모리)으로 전환돼 DB 핸드오프 키였던 preprocessed_at은
항상 NULL로 남는 죽은 컬럼이 됐다(→ 설계 04 §1.2). 저장 시점이 곧 전처리 완료이므로 별도
상태 컬럼이 불필요하다. ORM에서 함께 제거했다.

Revision ID: c6fd3e4b6185
Revises: b2d4f6a8c1e3
Create Date: 2026-06-11 20:46:39.768630

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c6fd3e4b6185'
down_revision: Union[str, Sequence[str], None] = 'b2d4f6a8c1e3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column('news', 'preprocessed_at')


def downgrade() -> None:
    """Downgrade schema."""
    # 미사용 컬럼이었으므로(항상 NULL) 복원해도 데이터 손실은 없다.
    op.add_column('news', sa.Column('preprocessed_at', sa.DateTime(), nullable=True))
