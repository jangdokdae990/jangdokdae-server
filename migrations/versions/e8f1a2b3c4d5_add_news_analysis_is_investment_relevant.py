"""add news_analysis.is_investment_relevant (relevance 필터)

비투자성 뉴스(홍보·사회공헌·ESG·마케팅·교육·부고/인사)를 분류 단계에서 가려내는 relevance 필터용
컬럼. false면 분류만 적재하고 issue_docent(콘텐츠)는 적재하지 않는다(평가 04). additive·기본값 true라
기존 행은 모두 관련 뉴스로 간주돼 안전하다. 수기 작성(.env/DB 없이 autogenerate 불가) —
app/db/orm_models/news_analysis.py와 일치.

Revision ID: e8f1a2b3c4d5
Revises: d7e9a1c2b3f4
Create Date: 2026-06-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e8f1a2b3c4d5'
down_revision: Union[str, Sequence[str], None] = 'd7e9a1c2b3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'news_analysis',
        sa.Column(
            'is_investment_relevant', sa.Boolean(),
            server_default=sa.text('true'), nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('news_analysis', 'is_investment_relevant')
