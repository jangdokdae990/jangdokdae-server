"""글로벌 지수 종목 유니버스 적재 — 유로스톡스50·닛케이225·항셍·CSI300 대표주를 company_entities에.

큐레이션 정적 데이터(FDR 미지원 지수)를 ``is_active=True``로 적재해 온보딩 관심 설정에 즉시
노출한다. ``corp_code=NULL``이라 DART 분석 수집(재무·공시·보고서)에는 섞이지 않는다.

사용:
    python -m scripts.sync_global_index_companies
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from app.db.base import AsyncSessionLocal
from app.db.orm_models.company_entity import CompanyEntity
from services.collector.global_index_company_collector import (
    sync_global_index_companies,
)


async def main() -> None:
    async with AsyncSessionLocal() as db:
        result = await sync_global_index_companies(db)
        total = await db.scalar(select(func.count()).select_from(CompanyEntity))
        print(f"[global-index] {result} | company_entities total={total}")


if __name__ == "__main__":
    asyncio.run(main())
