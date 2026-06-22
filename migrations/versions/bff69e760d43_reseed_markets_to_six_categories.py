"""reseed markets to six categories

Revision ID: bff69e760d43
Revises: 211e9d09101d
Create Date: 2026-06-22 09:50:04.574486

시장 마스터를 국내/해외 2분류에서 온보딩 화면 기준 6개(코스피·코스닥·나스닥·S&P500·미국ETF·
기타 해외)로 교체한다. code는 거래소/지수 식별자(<=10자)로 두고, 코스피/코스닥은
CompanyEntity.market(KOSPI/KOSDAQ)과 직접 매핑된다(app/db/queries.MARKET_CODE_TO_EXCHANGES).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'bff69e760d43'
down_revision: Union[str, Sequence[str], None] = '211e9d09101d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_markets = sa.table(
    "markets",
    sa.column("code", sa.String),
    sa.column("name_ko", sa.String),
    sa.column("name_en", sa.String),
    sa.column("is_active", sa.Boolean),
)

# 온보딩 시장 6종(전부 활성). created_at은 서버 기본값(KST_NOW)에 맡긴다.
_SIX_MARKETS = [
    {"code": "KOSPI", "name_ko": "코스피", "name_en": "KOSPI", "is_active": True},
    {"code": "KOSDAQ", "name_ko": "코스닥", "name_en": "KOSDAQ", "is_active": True},
    {"code": "NASDAQ", "name_ko": "나스닥", "name_en": "NASDAQ", "is_active": True},
    {"code": "SP500", "name_ko": "S&P 500", "name_en": "S&P 500", "is_active": True},
    {"code": "US_ETF", "name_ko": "미국 ETF", "name_en": "US ETF", "is_active": True},
    {
        "code": "GLOBAL",
        "name_ko": "기타 해외 시장",
        "name_en": "Other Global Markets",
        "is_active": True,
    },
]

_ORIGINAL_MARKETS = [
    {"code": "KR", "name_ko": "국내", "name_en": "Domestic", "is_active": True},
    {"code": "OVERSEAS", "name_ko": "해외", "name_en": "Overseas", "is_active": False},
]


def _reseed(rows: list[dict]) -> None:
    # 기존 시장을 참조하는 관심 행을 먼저 비운다(market_id FK는 cascade가 아님).
    op.execute("DELETE FROM user_interest_markets")
    op.execute("DELETE FROM markets")
    op.bulk_insert(_markets, rows)


def upgrade() -> None:
    """국내/해외 2분류 → 6개 시장으로 교체."""
    _reseed(_SIX_MARKETS)


def downgrade() -> None:
    """원래 국내/해외 2분류로 복원."""
    _reseed(_ORIGINAL_MARKETS)
