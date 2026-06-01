"""테이블별 UPSERT 공통 도구. 모든 수집 에이전트가 공유한다."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.orm_models.disclosure import Disclosure
from app.db.orm_models.financial_statement import FinancialStatement
from app.db.orm_models.market_indicator import MarketIndicator
from app.db.orm_models.news import News
from app.db.orm_models.stock_price import StockPrice


async def _upsert(
    db: AsyncSession, model: type[Base], records: list[dict], index_elements: list[str]
) -> int:
    """records를 UPSERT(충돌 무시)하고 새로 삽입된 건수를 반환. 빈 입력은 0."""
    if not records:
        return 0
    stmt = pg_insert(model).values(records).on_conflict_do_nothing(index_elements=index_elements)
    result = await db.execute(stmt)
    await db.commit()
    inserted: int = result.rowcount  # type: ignore[attr-defined]
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
