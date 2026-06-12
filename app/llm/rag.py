"""기업 컨텍스트 RAG 검색 — 사업보고서 청크에서 관련 컨텍스트를 찾아온다(설계 05 §7).

분석 단계 ImpactAnalysisChain의 related_companies 컨텍스트를 제공한다. report_chunks의
임베딩(ReportEmbedder가 채움)을 pgvector cosine 거리로 검색한다 — 별도 벡터 DB·langchain
PGVector 의존성 없이 EmbeddingClient(쿼리=RETRIEVAL_QUERY)와 ORM `<=>` 연산자만으로 처리해
중복 제거(deduplicator)의 raw pgvector 방식과 일관되게 둔다.

쿼리·문서를 다른 task_type으로 임베딩해 비대칭 검색을 만든다(05 §7.2: 청크는
RETRIEVAL_DOCUMENT로, 쿼리는 RETRIEVAL_QUERY로). 벡터 DB에 매칭이 없으면 빈 문자열을
반환해 호출부가 "확실치 않음"으로 처리하게 한다(멘토 RAG 엣지케이스 → 06 §6).
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.orm_models.report_chunk import ReportChunk
from services.embedder.embedding_client import EmbeddingClient

logger = logging.getLogger(__name__)


async def get_company_context(
    db: AsyncSession,
    company_name: str,
    k: int = 3,
    client: EmbeddingClient | None = None,
) -> str:
    """company_name 관련 사업보고서 청크 상위 k건을 cosine 유사도로 찾아 본문을 합쳐 반환한다.

    매칭이 없으면 빈 문자열을 반환한다. 임베딩 호출은 동기 블로킹이라 to_thread로 분리한다.
    """
    embed_client = client or EmbeddingClient()
    query = f"{company_name} 사업 현황 재무 요약"
    query_vector = (
        await asyncio.to_thread(embed_client.embed_documents, [query], "RETRIEVAL_QUERY")
    )[0]

    result = await db.execute(
        select(ReportChunk.content)
        .where(ReportChunk.embedding.is_not(None))
        .order_by(ReportChunk.embedding.cosine_distance(query_vector))
        .limit(k)
    )
    contents = list(result.scalars().all())
    if not contents:
        logger.info("기업 컨텍스트 미발견 company=%s", company_name)
        return ""
    return "\n".join(contents)
