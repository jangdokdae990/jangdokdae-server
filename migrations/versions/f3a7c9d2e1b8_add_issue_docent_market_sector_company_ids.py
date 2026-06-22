"""add issue_docent.market_ids / sector_ids / company_ids

발행 콘텐츠(issue_docent)를 온보딩 관심사(market/sector/company)로 필터링하기 위한 백필 컬럼을
추가한다 — market_ids(종목 거래소→markets.id), sector_ids(→sectors.id), company_ids(→company_entities.id).
관심사 `:id = ANY(...)` 조회 가속을 위해 GIN 인덱스를 함께 만든다. news_analysis의 동일 패턴을
미러링했고, 원문 태그(company_tags·sector_tags)는 news_analysis에 그대로 보존된다. 수기 작성
(.env/DB 없이 autogenerate 불가) — app/db/orm_models/issue_docent.py와 일치.

Revision ID: f3a7c9d2e1b8
Revises: e89f78e7e898
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a7c9d2e1b8'
down_revision: Union[str, Sequence[str], None] = 'e89f78e7e898'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ARRAY_COLUMNS = ('market_ids', 'sector_ids', 'company_ids')


def upgrade() -> None:
    """Upgrade schema."""
    for column in _ARRAY_COLUMNS:
        op.add_column(
            'issue_docent',
            sa.Column(
                column, sa.ARRAY(sa.Integer()),
                server_default=sa.text("'{}'::integer[]"), nullable=False,
            ),
        )
        op.create_index(
            f'ix_issue_docent_{column}', 'issue_docent', [column],
            unique=False, postgresql_using='gin',
        )


def downgrade() -> None:
    """Downgrade schema."""
    for column in reversed(_ARRAY_COLUMNS):
        op.drop_index(f'ix_issue_docent_{column}', table_name='issue_docent')
        op.drop_column('issue_docent', column)
