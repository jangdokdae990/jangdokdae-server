"""add news_analysis.company_ids / sector_ids backfill columns

분류 태그(이름)를 마스터로 해소한 백필 컬럼을 추가한다 — company_ids(→company_entities.id),
sector_ids(→sectors.id). "특정 기업/섹터를 언급한 이슈" 관계형 조회·주가 연동의 조인 키이며,
`:id = ANY(...)` 가속을 위해 GIN 인덱스를 함께 만든다. 원문 태그(company_tags·sector_tags)는
그대로 유지되므로 미매칭(마스터 미수록)에도 안전하다. 본 마이그레이션은 ORM 모델에 맞춰
수기 작성했다(.env/DB 없이 autogenerate 불가) — app/db/orm_models/news_analysis.py와 일치.

Revision ID: d7e9a1c2b3f4
Revises: a1b2c3d4e5f6
Create Date: 2026-06-16 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd7e9a1c2b3f4'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'news_analysis',
        sa.Column(
            'company_ids', sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"), nullable=False,
        ),
    )
    op.add_column(
        'news_analysis',
        sa.Column(
            'sector_ids', sa.ARRAY(sa.Integer()),
            server_default=sa.text("'{}'::integer[]"), nullable=False,
        ),
    )
    op.create_index(
        'ix_news_analysis_company_ids', 'news_analysis', ['company_ids'],
        unique=False, postgresql_using='gin',
    )
    op.create_index(
        'ix_news_analysis_sector_ids', 'news_analysis', ['sector_ids'],
        unique=False, postgresql_using='gin',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_news_analysis_sector_ids', table_name='news_analysis')
    op.drop_index('ix_news_analysis_company_ids', table_name='news_analysis')
    op.drop_column('news_analysis', 'sector_ids')
    op.drop_column('news_analysis', 'company_ids')
