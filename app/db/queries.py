"""DB 조회·갱신 쿼리 모음 — 파이프라인 단계 간 DB 접근을 한곳에 모은다.

임베딩·클러스터링 단계의 상태 핸드오프 쿼리를 둔다. 각 단계는 "미처리 레코드"만 집어가므로
부분 실패 후 재실행해도 남은 것만 처리된다(멱등).
"""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.news import News
from app.db.orm_models.report_chunk import ReportChunk


async def get_unembedded_news(db: AsyncSession) -> list[News]:
    """임베딩 대기 뉴스 조회 — is_filtered=FALSE AND embedding IS NULL.

    탈락분·기임베딩분은 제외돼 재실행해도 새 미임베딩분만 집어간다(멱등).
    """
    result = await db.execute(
        select(News)
        .where(News.is_filtered.is_(False))
        .where(News.embedding.is_(None))
        .order_by(News.id)
    )
    return list(result.scalars().all())


async def get_unembedded_report_chunks(db: AsyncSession) -> list[ReportChunk]:
    """임베딩 대기 사업보고서 청크 조회 — embedding IS NULL."""
    result = await db.execute(
        select(ReportChunk).where(ReportChunk.embedding.is_(None)).order_by(ReportChunk.id)
    )
    return list(result.scalars().all())


async def save_news_embeddings(db: AsyncSession, id_to_vector: dict[int, list[float]]) -> int:
    """뉴스 임베딩을 id별로 일괄 저장. 저장 건수를 반환(빈 입력은 0, DB 미접근)."""
    if not id_to_vector:
        return 0
    # SQLAlchemy 2.0 ORM 일괄 UPDATE(기본키 기준) — 행마다 UPDATE 문을 모아 1회 round-trip.
    await db.execute(
        update(News),
        [{"id": news_id, "embedding": vector} for news_id, vector in id_to_vector.items()],
    )
    await db.commit()
    return len(id_to_vector)


async def save_chunk_embeddings(db: AsyncSession, id_to_vector: dict[int, list[float]]) -> int:
    """사업보고서 청크 임베딩을 id별로 일괄 저장. 저장 건수를 반환(빈 입력은 0)."""
    if not id_to_vector:
        return 0
    await db.execute(
        update(ReportChunk),
        [{"id": chunk_id, "embedding": vector} for chunk_id, vector in id_to_vector.items()],
    )
    await db.commit()
    return len(id_to_vector)


async def get_clusterable_news(db: AsyncSession, since: datetime) -> list[News]:
    """클러스터링 대상 뉴스 조회 — 당일 수집·임베딩 완료·미탈락·비중복·미분석분.

    since(KST naive)는 수집 시각 하한 — 없으면 미분석 백로그 전체가 매일 재클러스터링된다.
    근접 중복·전처리 탈락·분석 완료 행은 제외한다.
    """
    result = await db.execute(
        select(News)
        .where(News.created_at >= since)
        .where(News.is_filtered.is_(False))
        .where(News.is_duplicate.is_(False))
        .where(News.is_analyzed.is_(False))
        .where(News.embedding.is_not(None))
        .order_by(News.id)
    )
    return list(result.scalars().all())
