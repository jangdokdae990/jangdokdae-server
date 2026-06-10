"""CompanyCollector — 기업 데이터 수집 단계 진입점 (Airflow Task, 정적 분기).

schedule 값에 따라 수집 대상을 분기한다(설계 03 §7.4):
    - "morning"/"afternoon": 당일·전일 공시 메타데이터 → disclosures
    - "macro":               이번 달 거시지표(금리·CPI·M2) → market_indicators
    - "quarterly":           전년도 재무제표 + 사업보고서 청크 → financial_statements·report_chunks

수집기 호출은 입출력이 고정이고 분기가 정적이라 LangGraph가 아니라 Airflow Task로 둔다
(설계 00 §5.1). 단계끼리 직접 호출하지 않고 공유 DB로만 핸드오프하므로, 각 수집기
산출물을 save_tool로 즉시 멱등 저장한다. 주가·환율은 적재하지 않는다(분석 시점 on-demand).
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import AsyncSessionLocal
from services.collector.dart_collector import DARTCollector
from services.collector.financial_collector import FinancialCollector
from services.collector.macro_collector import MacroCollector
from services.collector.report_collector import ReportCollector
from services.collector.stock_symbols import StockSymbol
from services.collector.tools.company_loader import load_active_companies
from services.collector.tools.save_tool import (
    upsert_disclosures,
    upsert_financial_statements,
    upsert_market_indicators,
    upsert_report_chunks,
)
from utils.dates import now_kst

logger = logging.getLogger(__name__)

DAILY_SCHEDULES = frozenset({"morning", "afternoon"})


class CompanyCollector:
    """schedule 분기로 기업 데이터를 수집·저장하는 파이프라인 단계."""

    async def run(
        self,
        schedule: str,
        *,
        bsns_year: int | None = None,
        db: AsyncSession | None = None,
    ) -> dict[str, object]:
        """schedule에 따라 수집을 분기 실행. db 미지정 시 세션을 직접 연다(Airflow Task용)."""
        if db is not None:
            return await self._run(schedule, bsns_year, db)
        async with AsyncSessionLocal() as session:
            return await self._run(schedule, bsns_year, session)

    async def _run(
        self, schedule: str, bsns_year: int | None, db: AsyncSession
    ) -> dict[str, object]:
        companies = await load_active_companies(db)
        if schedule in DAILY_SCHEDULES:
            saved = await self._collect_disclosures(db, companies)
        elif schedule == "macro":
            saved = await self._collect_macro(db)
        elif schedule == "quarterly":
            saved = await self._collect_quarterly(db, companies, bsns_year)
        else:
            raise ValueError(f"알 수 없는 schedule: {schedule!r}")
        logger.info("CompanyCollector 완료 schedule=%s saved=%s", schedule, saved)
        return {"schedule": schedule, "saved": saved}

    async def _collect_disclosures(
        self, db: AsyncSession, companies: list[StockSymbol]
    ) -> dict[str, int]:
        # 전일~당일을 함께 조회해 장 마감 후·야간 공시 누락을 막는다(중복은 ON CONFLICT로 멱등).
        today = now_kst().date()
        bgn_de = (today - timedelta(days=1)).strftime("%Y%m%d")
        end_de = today.strftime("%Y%m%d")
        collected = await DARTCollector(companies).collect(bgn_de, end_de)
        n = await upsert_disclosures(db, [c.to_record() for c in collected])
        return {"disclosures": n}

    async def _collect_macro(self, db: AsyncSession) -> dict[str, int]:
        ym = now_kst().strftime("%Y%m")  # 이번 달 1건 (월별 incremental)
        collected = await MacroCollector().collect_ecos(ym, ym)
        n = await upsert_market_indicators(db, [c.to_record() for c in collected])
        return {"market_indicators": n}

    async def _collect_quarterly(
        self, db: AsyncSession, companies: list[StockSymbol], bsns_year: int | None
    ) -> dict[str, int]:
        # 사업보고서는 다음 해 3월에 제출되므로 분기 첫날 기준 최신 확정본은 전년도.
        year = bsns_year if bsns_year is not None else now_kst().year - 1
        financials, chunks = await asyncio.gather(
            FinancialCollector(companies).collect(year),
            ReportCollector(companies).collect(year),
        )
        fin_n = await upsert_financial_statements(db, [f.to_record() for f in financials])
        chunk_n = await upsert_report_chunks(db, [c.to_record() for c in chunks])
        return {"financial_statements": fin_n, "report_chunks": chunk_n}
