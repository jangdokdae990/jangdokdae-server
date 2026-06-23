"""add global index markets (eurostoxx/nikkei/hangseng/csi300)

Revision ID: c4e8b1a9f2d6
Revises: 8fa49d43cd33
Create Date: 2026-06-23 00:00:00.000000

온보딩 시장 마스터에 글로벌 지수 4종(유로스톡스50·닛케이225·항셍·CSI300)을 추가한다.
code는 지수 식별자(<=10자)이고, CompanyEntity.market(EUROSTOXX/NIKKEI/HANGSENG/CSI300)과
직접 매핑된다(app/db/queries.MARKET_CODE_TO_EXCHANGES). 종목은
services/collector/global_index_company_collector.py가 별도 적재한다.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4e8b1a9f2d6"
down_revision: str | Sequence[str] | None = "8fa49d43cd33"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_markets = sa.table(
    "markets",
    sa.column("code", sa.String),
    sa.column("name_ko", sa.String),
    sa.column("name_en", sa.String),
    sa.column("is_active", sa.Boolean),
)

# 글로벌 지수 4종. 온보딩에선 GLOBAL(기타 해외) 칩 하나로 묶어 노출하므로 개별 시장은
# is_active=False로 시드해 칩에서 가린다(get_active_markets는 활성만 반환). 종목 자체는
# company_entities에 is_active=True로 적재돼 GLOBAL 필터로 잡힌다(queries.MARKET_CODE_TO_EXCHANGES).
# created_at은 서버 기본값(KST_NOW)에 맡긴다.
_GLOBAL_MARKETS = [
    {
        "code": "EUROSTOXX",
        "name_ko": "유로스톡스50",
        "name_en": "EURO STOXX 50",
        "is_active": False,
    },
    {"code": "NIKKEI", "name_ko": "닛케이225", "name_en": "Nikkei 225", "is_active": False},
    {"code": "HANGSENG", "name_ko": "항셍", "name_en": "Hang Seng", "is_active": False},
    {"code": "CSI300", "name_ko": "중국 CSI300", "name_en": "CSI 300", "is_active": False},
]
_CODES = tuple(market["code"] for market in _GLOBAL_MARKETS)


def upgrade() -> None:
    op.bulk_insert(_markets, _GLOBAL_MARKETS)


def downgrade() -> None:
    bind = op.get_bind()
    markets = sa.table("markets", sa.column("id", sa.Integer), sa.column("code", sa.String))
    ids = bind.execute(sa.select(markets.c.id).where(markets.c.code.in_(_CODES))).scalars().all()
    if ids:
        interests = sa.table("user_interest_markets", sa.column("market_id", sa.Integer))
        bind.execute(sa.delete(interests).where(interests.c.market_id.in_(ids)))
    bind.execute(sa.delete(markets).where(markets.c.code.in_(_CODES)))
