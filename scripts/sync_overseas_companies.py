"""해외 종목 유니버스 적재 — FDR로 S&P500 + NASDAQ-100 + 미국 ETF를 company_entities에.

해외는 ``is_active=True``로 적재돼 온보딩 관심 설정에 즉시 노출된다. ``corp_code=NULL``이라
DART 분석 수집(재무·공시·보고서)에는 섞이지 않는다(설계 docs/design/13).

사용:
    python -m scripts.sync_overseas_companies
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.db.base import AsyncSessionLocal
from app.db.orm_models.company_entity import CompanyEntity
from services.collector.overseas_company_collector import sync_overseas_companies


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await sync_overseas_companies(db)
        total = await db.scalar(select(func.count()).select_from(CompanyEntity))
        print(f"[overseas] {result} | company_entities total={total}")


if __name__ == "__main__":
    asyncio.run(main())
