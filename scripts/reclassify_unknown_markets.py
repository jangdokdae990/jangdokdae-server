"""market='UNKNOWN' 국내 종목 재분류 — FDR KRX 리스팅으로 실거래소 재매칭, 미해결은 비활성.

UNKNOWN은 PyKRX KOSPI/KOSDAQ 분류에서 못 찾은 종목(KONEX·신규/상장폐지 등)이다. 해외 적재 전
또는 후 어느 시점에 실행해도 안전하다(국내 종목만 대상, 멱등).

사용:
    python -m scripts.reclassify_unknown_markets
"""

from __future__ import annotations

import asyncio

from app.db.base import AsyncSessionLocal
from services.collector.company_master_collector import reclassify_unknown_markets


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await reclassify_unknown_markets(db)
        print(f"[reclassify] {result}")


if __name__ == "__main__":
    asyncio.run(main())
