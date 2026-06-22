"""add news.reprint_count (전재 매체 수 — 화제성 신호, 파생 컬럼)

같은 기사를 전재(재게재)한 매체 수를 보존하는 파생 데이터 컬럼(→ 설계 01 §5 · 05 §6).
단계 간 계약(게이트)이 아니며 어떤 단계도 읽는 조건으로 쓰지 않는다 — 중요도 스코어가
참고만 한다. 다층 중복 제거(GUID·URL·제목 Jaccard·cosine)로 묶인 동일 기사군의 매체 수,
중복 미검출 기본값 0.

Revision ID: 1cdcb76394bf
Revises: fa6e579bc7dc
Create Date: 2026-06-19 10:27:40.913148

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1cdcb76394bf'
down_revision: Union[str, Sequence[str], None] = 'fa6e579bc7dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 기존 행은 server_default('0')으로 채워져 NOT NULL을 만족한다.
    op.add_column(
        'news',
        sa.Column('reprint_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('news', 'reprint_count')
