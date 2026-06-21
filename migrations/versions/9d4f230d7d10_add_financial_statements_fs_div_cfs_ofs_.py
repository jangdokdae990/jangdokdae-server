"""add financial_statements.fs_div (CFS/OFS source)

수치 출처 재무제표 구분(CFS=연결 / OFS=개별)을 보존하는 추적 컬럼(→ 설계 03).
financial_collector가 CFS 우선·OFS 폴백으로 집은 출처를 기록해, 연도 간 비교 시
연결/개별 혼선을 방지한다. 구버전 적재분은 NULL(미상).

Revision ID: 9d4f230d7d10
Revises: 307cade08bba
Create Date: 2026-06-19 10:56:06.132665

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '9d4f230d7d10'
down_revision: Union[str, Sequence[str], None] = '307cade08bba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 분석(06) 테이블(issue_docent·news_analysis)은 아직 ORM 미모델링이라 autogenerate가
    # 삭제로 오인하나 타 파트 자산이므로 건드리지 않는다 — fs_div 추가만 적용한다.
    op.add_column('financial_statements', sa.Column('fs_div', sa.String(length=3), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('financial_statements', 'fs_div')
