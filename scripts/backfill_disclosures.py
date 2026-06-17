"""공시·재무·사업보고서 backfill — 과거 N년치 1회 적재.

ON CONFLICT DO NOTHING이라 중단 후 재실행해도 안전하다(멱등). 주가·환율은 on-demand
조회 대상이라 backfill하지 않는다.

사용:
    python -m scripts.backfill_disclosures [years]   # years 기본 3
"""

import asyncio
import sys

from app.db.base import AsyncSessionLocal
from services.collector.dart_collector import DARTCollector
from services.collector.financial_collector import FinancialCollector
from services.collector.report_collector import ReportCollector
from services.collector.tools.company_loader import load_active_companies
from services.collector.tools.save_tool import (
    upsert_disclosures,
    upsert_financial_statements,
    upsert_report_chunks,
)
from utils.dates import now_kst


async def backfill(years: int = 3) -> dict[str, int]:
    """추적 기업의 과거 years년치 공시·재무제표·사업보고서 청크를 적재하고 건수를 반환."""
    now = now_kst()
    bgn_de = f"{now.year - years}0101"
    end_de = now.strftime("%Y%m%d")
    async with AsyncSessionLocal() as db:
        companies = await load_active_companies(db)
        disclosures = await DARTCollector(companies).collect(bgn_de, end_de)
        d_n = await upsert_disclosures(db, [c.to_record() for c in disclosures])
        # 재무·사업보고서는 사업연도 단위 API라 연도별로 순회 수집한다.
        # 두 수집기는 독립 엔드포인트라 연도마다 병렬 수집한다.
        financial_collector = FinancialCollector(companies)
        report_collector = ReportCollector(companies)
        f_n = r_n = 0
        for year in range(now.year - years, now.year):
            financials, chunks = await asyncio.gather(
                financial_collector.collect(year),
                report_collector.collect(year),
            )
            f_n += await upsert_financial_statements(db, [f.to_record() for f in financials])
            r_n += await upsert_report_chunks(db, [c.to_record() for c in chunks])
    result = {"disclosures": d_n, "financial_statements": f_n, "report_chunks": r_n}
    print(f"disclosures backfill ({bgn_de}~{end_de}): {result}")
    return result


if __name__ == "__main__":
    arg_years = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    asyncio.run(backfill(arg_years))
