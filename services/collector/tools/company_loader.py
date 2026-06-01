"""DB에서 추적 기업 목록을 로드하는 유틸리티.

company_entities 테이블(is_active=True)을 읽어 수집기가 사용하는 StockSymbol 목록을 반환한다.
수집기들은 StockSymbol 인터페이스를 유지하므로 내부 로직 변경 없이 DB 기반으로 전환 가능.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.company_entity import CompanyEntity
from services.collector.stock_symbols import StockSymbol


async def load_active_companies(db: AsyncSession) -> list[StockSymbol]:
    """is_active=True인 기업을 stock_code 순으로 반환."""
    result = await db.execute(
        select(CompanyEntity)
        .where(CompanyEntity.is_active.is_(True))
        .order_by(CompanyEntity.stock_code)
    )
    entities = result.scalars().all()
    return [
        StockSymbol(
            stock_code=entity.stock_code,
            name=entity.name_ko,
            corp_code=entity.corp_code or "",
        )
        for entity in entities
    ]
