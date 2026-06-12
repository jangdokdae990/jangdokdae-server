"""뉴스 임베딩 — 전처리 통과분 제목을 벡터화해 news.embedding에 채운다(설계 05 §2).

입력은 **제목 단독**(build_embed_text). 주식 뉴스 제목은 핵심 키워드 밀도가 높아 title만으로
동일 이슈를 묶는 데 실용적으로 충분하고, 본문 fetch(클러스터링 단계 전체 ~31배 비용)를
피한다(05 §2.2, 실험2로 재확인). 임베딩 task_type은 CLUSTERING — 뉴스 군집화 용도.

상태 핸드오프: is_filtered=FALSE AND embedding IS NULL만 집어가므로(queries) 재실행해도
새로 수집된 미임베딩분만 처리된다(멱등, 설계 01 §2).
"""

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.queries import get_unembedded_news, save_news_embeddings
from services.embedder.embedding_client import LazyClientMixin

logger = logging.getLogger(__name__)


def build_embed_text(title: str) -> str:
    """뉴스 임베딩 입력 텍스트를 만든다 — 제목 단독(설계 05 §2.2)."""
    return title


class NewsEmbedder(LazyClientMixin):
    """미임베딩 뉴스를 배치 임베딩해 news.embedding에 저장하는 임베더."""

    async def embed_news(self, db: AsyncSession) -> int:
        """임베딩 대기 뉴스를 임베딩·저장하고 처리 건수를 반환한다.

        임베딩 호출(langchain embed_documents)은 동기 블로킹이라 to_thread로 빼
        이벤트 루프를 막지 않는다 — embed_news ∥ embed_chunks 병렬(설계 05 §8.3)의 전제.
        """
        rows = await get_unembedded_news(db)
        if not rows:
            return 0
        texts = [build_embed_text(row.title) for row in rows]
        vectors = await asyncio.to_thread(self.client.embed_documents, texts, "CLUSTERING")
        await save_news_embeddings(db, dict(zip((row.id for row in rows), vectors, strict=True)))
        logger.info("뉴스 임베딩 완료 count=%d model=%s", len(rows), self.client.model_name)
        return len(rows)
