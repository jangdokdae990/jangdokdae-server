"""add market description and tags

Revision ID: 6f6d98640ef9
Revises: bff69e760d43
Create Date: 2026-06-22 09:55:42.326677

온보딩 시장 카드에 표시할 description(설명)·tags(대표 종목) 컬럼을 추가하고 6개 시장을 채운다.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "6f6d98640ef9"
down_revision: Union[str, Sequence[str], None] = "bff69e760d43"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_markets = sa.table(
    "markets",
    sa.column("code", sa.String),
    sa.column("description", sa.String),
    sa.column("tags", postgresql.ARRAY(sa.Text)),
)

# 온보딩 카드용 설명·대표 종목 태그(code 기준).
_CARD_DATA = [
    {
        "code": "KOSPI",
        "description": "국내 대표 대형주 중심의 종합 주식 시장",
        "tags": ["삼성전자", "SK하이닉스"],
    },
    {
        "code": "KOSDAQ",
        "description": "성장 기업 중심의 중소형 주식 시장",
        "tags": ["에코프로비엠", "알테오젠"],
    },
    {
        "code": "NASDAQ",
        "description": "미국 기술주 중심의 주식 시장",
        "tags": ["애플", "마이크로소프트"],
    },
    {
        "code": "SP500",
        "description": "미국 주요 500개 기업으로 구성된 대표 지수",
        "tags": ["엔비디아", "아마존"],
    },
    {
        "code": "US_ETF",
        "description": "다양한 테마와 자산에 투자하는 상장지수펀드",
        "tags": ["SPY", "QQQ", "VOO"],
    },
    {
        "code": "GLOBAL",
        "description": "유럽, 일본, 중국 등 글로벌 주식 시장",
        "tags": ["유로스톡스", "닛케이", "항셍"],
    },
]


def upgrade() -> None:
    op.add_column("markets", sa.Column("description", sa.String(length=200), nullable=True))
    op.add_column(
        "markets",
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
    )
    for row in _CARD_DATA:
        op.execute(
            _markets.update()
            .where(_markets.c.code == row["code"])
            .values(description=row["description"], tags=row["tags"])
        )


def downgrade() -> None:
    op.drop_column("markets", "tags")
    op.drop_column("markets", "description")
