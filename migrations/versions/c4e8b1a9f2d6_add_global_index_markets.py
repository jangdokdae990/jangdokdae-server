"""add global index markets

Revision ID: c4e8b1a9f2d6
Revises: 8fa49d43cd33
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
