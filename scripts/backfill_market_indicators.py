"""거시지표 backfill — 과거 N년치 금리·CPI·M2(ECOS) 1회 적재.

ON CONFLICT DO NOTHING이라 중단 후 재실행해도 안전하다(멱등).

사용:
    python -m scripts.backfill_market_indicators [years]   # years 기본 5
"""

import asyncio
import sys

from app.db.base import AsyncSessionLocal
from services.collector.macro_collector import MacroCollector
from services.collector.tools.save_tool import upsert_market_indicators
from utils.dates import now_kst


async def backfill(years: int = 5) -> int:
    """현재로부터 years년 전부터 이번 달까지 ECOS 거시지표를 적재하고 삽입 건수를 반환."""
    now = now_kst()
    bgn_ym = f"{now.year - years}{now.month:02d}"
    end_ym = now.strftime("%Y%m")
    collected = await MacroCollector().collect_ecos(bgn_ym, end_ym)
    async with AsyncSessionLocal() as db:
        n = await upsert_market_indicators(db, [c.to_record() for c in collected])
    print(f"market_indicators backfill: {n}건 적재 ({bgn_ym}~{end_ym})")
    return n


if __name__ == "__main__":
    arg_years = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    asyncio.run(backfill(arg_years))
