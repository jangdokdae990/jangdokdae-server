"""테이블별 UPSERT 공통 도구. 모든 수집 에이전트가 공유한다."""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import News


async def upsert_news(db: AsyncSession, records: list[dict]) -> int:
    """뉴스 레코드를 url 기준 UPSERT(중복은 무시). 새로 삽입된 건수를 반환한다.

    records는 CollectedNews.to_record() 형식의 dict 리스트.
    created_at·is_analyzed 등 누락 컬럼은 DB server_default가 채운다.
    """
    if not records:
        return 0
    stmt = pg_insert(News).values(records).on_conflict_do_nothing(index_elements=["url"])
    result = await db.execute(stmt)
    await db.commit()
    inserted: int = result.rowcount  # type: ignore[attr-defined]
    return inserted
