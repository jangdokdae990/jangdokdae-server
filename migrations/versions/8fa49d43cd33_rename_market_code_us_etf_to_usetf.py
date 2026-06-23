"""rename market code US_ETF to USETF

Revision ID: 8fa49d43cd33
Revises: f3a7c9d2e1b8
Create Date: 2026-06-23 10:19:17.847206

미국 ETF 시장 코드를 다른 코드(KOSPI·SP500 등)처럼 구분자 없는 ``USETF``로 통일한다.
``markets.code``와 ``company_entities.market``은 ``resolve_market_ids``에서 직접 조인되므로
(``CompanyEntity.market == Market.code``) 두 컬럼을 함께 갱신해야 정합성이 깨지지 않는다.
``user_interest_markets``는 ``market_id`` FK라 코드 변경의 영향을 받지 않는다.
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8fa49d43cd33'
down_revision: Union[str, Sequence[str], None] = 'f3a7c9d2e1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE markets SET code = 'USETF' WHERE code = 'US_ETF'")
    op.execute("UPDATE company_entities SET market = 'USETF' WHERE market = 'US_ETF'")


def downgrade() -> None:
    op.execute("UPDATE company_entities SET market = 'US_ETF' WHERE market = 'USETF'")
    op.execute("UPDATE markets SET code = 'US_ETF' WHERE code = 'USETF'")
