"""reseed markets to exchange/index taxonomy (KR/OVERSEAS → KOSPI…GLOBAL)

market 마스터를 운영 DB 정본인 거래소·지수 6종으로 재시드한다 — 구 KR/OVERSEAS 2종(시드
211e9d09101d)과 어긋난 코드/DB 불일치를 해소한다(설계 14). DELETE(구 코드) + INSERT … ON
CONFLICT (code) DO NOTHING으로 멱등 적용해, 운영 DB(이미 6행)와 fresh DB(KR/OVERSEAS)를 같은
상태로 수렴시킨다. id는 환경별로 다를 수 있으나 FK가 id를 참조하므로 무방하다. 수기 작성
(.env/DB 없이 autogenerate 불가).

Revision ID: c2b5e8a4d017
Revises: f3a7c9d2e1b8
Create Date: 2026-06-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c2b5e8a4d017'
down_revision: Union[str, Sequence[str], None] = 'f3a7c9d2e1b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 정본 6-market (code, name_ko, name_en) — 전부 is_active=true.
_MARKETS = (
    ('KOSPI', '코스피', 'KOSPI'),
    ('KOSDAQ', '코스닥', 'KOSDAQ'),
    ('NASDAQ', '나스닥', 'NASDAQ'),
    ('SP500', 'S&P 500', 'S&P 500'),
    ('US_ETF', '미국 ETF', 'US ETF'),
    ('GLOBAL', '기타 해외 시장', 'Other Global Markets'),
)


def _values_sql() -> str:
    rows = []
    for code, name_ko, name_en in _MARKETS:
        ko = name_ko.replace("'", "''")
        en = name_en.replace("'", "''")
        rows.append(f"('{code}', '{ko}', '{en}', true)")
    return ", ".join(rows)


def upgrade() -> None:
    """Upgrade schema."""
    # 구 시드(KR/OVERSEAS) 제거 — 운영 DB엔 이미 없고, fresh DB에선 참조자가 없어 안전.
    op.execute("DELETE FROM markets WHERE code IN ('KR', 'OVERSEAS')")
    # 6-market 멱등 삽입 — 운영 DB의 기존 행과 code 충돌 시 건너뛴다.
    op.execute(
        "INSERT INTO markets (code, name_ko, name_en, is_active) VALUES "
        f"{_values_sql()} ON CONFLICT (code) DO NOTHING"
    )


def downgrade() -> None:
    """Downgrade schema."""
    codes = ", ".join(f"'{code}'" for code, _, _ in _MARKETS)
    op.execute(f"DELETE FROM markets WHERE code IN ({codes})")
    op.execute(
        "INSERT INTO markets (code, name_ko, name_en, is_active) VALUES "
        "('KR', '국내', 'Domestic', true), "
        "('OVERSEAS', '해외', 'Overseas', false) "
        "ON CONFLICT (code) DO NOTHING"
    )
