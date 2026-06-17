"""종목 유니버스 동기화 — 전 상장사 적재 + KOSPI200 추적 활성화.

DART corpCode(전 상장사) + PyKRX(섹터·마켓)로 ``company_entities``를 동기화하고,
KRX KOSPI200 구성종목을 ``is_active=True``로 승격한다(나머지는 비활성). 신규 상장사는
sync 단계에서 ``is_active=False``로 들어오므로, 추적 유니버스는 이 스크립트가 단일 출처다.

pykrx는 KRX 로그인이 필요하다 — ``.env``의 ``KRX_ID``/``KRX_PW``가 있어야 하며, ``app.config``
import 시 그 값이 ``os.environ``으로 bridge된다(pykrx가 os.environ을 직접 읽기 때문).

사용:
    python -m scripts.sync_company_master
"""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select, update

from app.db.base import AsyncSessionLocal  # import 시 app.config가 KRX 자격을 os.environ에 bridge
from app.db.orm_models.company_entity import CompanyEntity
from services.collector.company_master_collector import sync_company_master
from utils.dates import now_kst

KOSPI200_INDEX = "1028"  # KRX 지수 코드(코스피200)


async def main() -> None:
    # config(os.environ KRX bridge)가 로드된 뒤 import해야 pykrx 자동 로그인이 인증된다
    from pykrx import stock

    async with AsyncSessionLocal() as db:
        result = await sync_company_master(db)
        total = await db.scalar(select(func.count()).select_from(CompanyEntity))
        print(f"[sync] {result} | company_entities total={total}")

        day = now_kst().strftime("%Y%m%d")
        raw = await asyncio.to_thread(stock.get_index_portfolio_deposit_file, KOSPI200_INDEX, day)
        codes = [str(c).zfill(6) for c in (raw or [])]
        if not codes:
            raise RuntimeError("KOSPI200 구성종목 조회 실패 — .env의 KRX_ID/KRX_PW 확인")

        # 추적 유니버스를 KOSPI200으로 재설정(기존 활성 해제 후 재승격 → 지수 편출입 반영)
        await db.execute(update(CompanyEntity).values(is_active=False))
        promoted = await db.execute(
            update(CompanyEntity).where(CompanyEntity.stock_code.in_(codes)).values(is_active=True)
        )
        await db.commit()

        active = await db.scalar(
            select(func.count()).select_from(CompanyEntity).where(CompanyEntity.is_active.is_(True))
        )
        print(f"[KOSPI200] {len(codes)}종목 → 승격 {promoted.rowcount} | is_active=True: {active}")


if __name__ == "__main__":
    asyncio.run(main())
