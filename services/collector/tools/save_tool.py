"""테이블별 UPSERT 공통 도구 — 모든 수집기·에이전트가 공유하는 DB 저장 경계.

역할:
    각 수집기의 to_record() 산출물(list[dict])을 받아 PostgreSQL ON CONFLICT
    DO NOTHING으로 멱등 저장한다. 테이블별 충돌 키(url, rcept_no, (stock_code,date) 등)를
    upsert_* 함수가 캡슐화하므로 호출부는 충돌 규칙을 몰라도 된다.

핵심 동작:
    - _upsert(): 빈 입력은 0 반환(=DB 미접근, db=None 테스트 허용). 대량 입력은
      PostgreSQL 바인드 파라미터 상한(65,535)을 넘지 않도록 (행수×컬럼수) 기준으로
      청크 분할하되, 전체를 1회 commit해 배치 원자성을 유지한다.
    - DO NOTHING이므로 충돌 행은 '무시'된다 — 기존 값 보정(update)은 하지 않는다.

대상 테이블:
    news / stock_prices / disclosures / market_indicators / financial_statements / report_chunks.
"""

from collections.abc import Iterator

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.orm_models.disclosure import Disclosure
from app.db.orm_models.financial_statement import FinancialStatement
from app.db.orm_models.market_indicator import MarketIndicator
from app.db.orm_models.news import News
from app.db.orm_models.report_chunk import ReportChunk
from app.db.orm_models.stock_price import StockPrice

# PostgreSQL 바인드 파라미터 상한(65,535) 회피용 안전 마진.
# 1회 멀티로우 INSERT의 파라미터 수 = 행 수 × 컬럼 수 → 컬럼 수로 나눠 청크 크기를 정한다.
_MAX_BIND_PARAMS = 30000


def _chunks(records: list[dict], max_params: int | None = None) -> Iterator[list[dict]]:
    """records를 INSERT 파라미터 한계(행×컬럼) 이하 청크로 분할. 호출자가 비어있지 않음을 보장."""
    limit = _MAX_BIND_PARAMS if max_params is None else max_params
    chunk_size = max(1, limit // len(records[0]))
    for start in range(0, len(records), chunk_size):
        yield records[start : start + chunk_size]


async def _upsert(
    db: AsyncSession, model: type[Base], records: list[dict], index_elements: list[str]
) -> int:
    """records를 UPSERT(충돌 무시)하고 새로 삽입된 건수를 반환. 빈 입력은 0.

    대량 입력은 파라미터 한계를 넘지 않도록 청크로 나눠 실행하되, 전체를 1회 commit해
    배치 원자성을 유지한다(중간 청크 실패 시 모두 롤백).
    """
    if not records:
        return 0
    inserted = 0
    for chunk in _chunks(records):
        stmt = pg_insert(model).values(chunk).on_conflict_do_nothing(index_elements=index_elements)
        result = await db.execute(stmt)
        inserted += result.rowcount  # type: ignore[attr-defined]
    await db.commit()
    return inserted


async def upsert_news(db: AsyncSession, records: list[dict]) -> int:
    """뉴스 레코드를 url 기준 UPSERT. records는 CollectedNews.to_record() 형식."""
    return await _upsert(db, News, records, ["url"])


async def upsert_stock_prices(db: AsyncSession, records: list[dict]) -> int:
    """주가 레코드를 (stock_code, date) 기준 UPSERT. records는 CollectedPrice.to_record() 형식."""
    return await _upsert(db, StockPrice, records, ["stock_code", "date"])


async def upsert_disclosures(db: AsyncSession, records: list[dict]) -> int:
    """공시 레코드를 rcept_no 기준 UPSERT. records는 CollectedDisclosure.to_record() 형식."""
    return await _upsert(db, Disclosure, records, ["rcept_no"])


async def upsert_market_indicators(db: AsyncSession, records: list[dict]) -> int:
    """거시지표를 (indicator_type, currency, date) 기준 UPSERT."""
    return await _upsert(db, MarketIndicator, records, ["indicator_type", "currency", "date"])


async def upsert_financial_statements(db: AsyncSession, records: list[dict]) -> int:
    """재무제표를 (corp_code, year, quarter) 기준 UPSERT."""
    return await _upsert(db, FinancialStatement, records, ["corp_code", "year", "quarter"])


async def upsert_report_chunks(db: AsyncSession, records: list[dict]) -> int:
    """사업보고서 청크를 (corp_code, report_year, chunk_type, subsection) 기준 UPSERT."""
    keys = ["corp_code", "report_year", "chunk_type", "subsection"]
    return await _upsert(db, ReportChunk, records, keys)
