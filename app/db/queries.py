"""DB 조회·갱신 쿼리 모음 — 파이프라인 단계 간 DB 접근을 한곳에 모은다."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.news import News


async def fetch_unprocessed_news(db: AsyncSession, limit: int) -> list[News]:
    """전처리 미완료(preprocessed_at IS NULL) 뉴스를 id 순으로 limit개 조회."""
    result = await db.execute(
        select(News).where(News.preprocessed_at.is_(None)).order_by(News.id).limit(limit)
    )
    return list(result.scalars().all())


async def mark_news_preprocessed(
    db: AsyncSession,
    news_id: int,
    *,
    url: str,
    title: str,
    preprocessed_at: datetime,
    is_filtered: bool,
) -> None:
    """전처리 결과를 뉴스 1건에 반영. 정제된 title·url과 처리 시각·필터 여부를 기록.

    commit은 호출부(배치 단위)에서 수행한다.
    """
    await db.execute(
        update(News)
        .where(News.id == news_id)
        .values(
            url=url,
            title=title,
            preprocessed_at=preprocessed_at,
            is_filtered=is_filtered,
        )
    )
