"""사업보고서 청크 임베딩 — RAG 소스 준비.

embedding IS NULL 청크를 임베딩해 분석 단계의 기업 컨텍스트를 제공한다. 입력은 청크 본문
전체(content)이며, task_type은 RETRIEVAL_DOCUMENT — 쿼리(RETRIEVAL_QUERY)와 비대칭 매칭한다.
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.queries import get_unembedded_report_chunks, save_chunk_embeddings
from services.embedder.embedding_client import LazyClientMixin

logger = logging.getLogger(__name__)


class ReportEmbedder(LazyClientMixin):
    """미임베딩 사업보고서 청크를 배치 임베딩해 report_chunks.embedding에 저장하는 임베더."""

    async def embed_chunks(self, db: AsyncSession) -> int:
        """임베딩 대기 청크를 임베딩·저장하고 처리 건수를 반환한다(멱등, 미임베딩분만)."""
        rows = await get_unembedded_report_chunks(db)
        if not rows:
            return 0
        texts = [row.content for row in rows]
        vectors = await asyncio.to_thread(
            self.client.embed_documents, texts, "RETRIEVAL_DOCUMENT"
        )
        await save_chunk_embeddings(db, dict(zip((row.id for row in rows), vectors, strict=True)))
        logger.info("사업보고서 청크 임베딩 완료 count=%d model=%s", len(rows), self.client.model_name)  # noqa: E501
        return len(rows)
