"""EmbeddingClusterer — 임베딩·중복제거·클러스터링·이슈 선정 단계 조립.

흐름: (embed_news ∥ embed_chunks) → deduplicate → cluster → score_and_select.
공유 DB 상태 컬럼(embedding·is_duplicate·news_cluster)으로만 핸드오프한다.

세션 주의: 두 임베딩을 병렬 실행하되 AsyncSession은 동시 사용이 안전하지 않으므로 각자
독립 세션을 연다. 이후 중복제거·클러스터링·적재는 넘겨받은 db 하나로 순차 처리한다.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TypedDict

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.queries import get_clusterable_news
from services.embedder.cluster import cluster_news, order_by_centrality, promote_singletons
from services.embedder.embedding_client import EmbeddingClient
from services.embedder.news_embedder import NewsEmbedder
from services.embedder.report_embedder import ReportEmbedder
from services.embedder.score import ClusterScore, persist_clusters, score_cluster
from services.preprocessor.deduplicator import flag_duplicates_by_similarity
from utils.dates import now_kst

logger = logging.getLogger(__name__)


class EmbeddingClustererState(TypedDict):
    """단계 실행 결과 요약 — 카운트와 실패 신호만 담는다(데이터는 DB 핸드오프)."""

    news_embedded: int        # 임베딩 생성된 뉴스 수
    chunks_embedded: int      # 임베딩 생성된 ReportChunk 수
    duplicates_removed: int   # 근접 중복 soft flag 수
    clusters_formed: int      # 형성된 클러스터 수(싱글톤 포함)
    top_issues: list[int]     # 분석 파이프라인에 넘길 대표 기사 id 목록
    errors: list[str]         # 부분 실패 신호(빈 리스트=전부 성공)


class EmbeddingClusterer:
    """임베딩→중복제거→클러스터링→이슈 선정을 조립하는 단계."""

    def __init__(
        self,
        embedding_client: EmbeddingClient | None = None,
        news_embedder: NewsEmbedder | None = None,
        report_embedder: ReportEmbedder | None = None,
    ) -> None:
        # 클라이언트를 명시 주입하면 두 임베더가 공유한다(무거운 백엔드).
        # 미주입(None)이면 각 임베더가 작업이 있을 때만 lazy 생성한다.
        self.news_embedder = news_embedder or NewsEmbedder(embedding_client)
        self.report_embedder = report_embedder or ReportEmbedder(embedding_client)

    async def run(self, db: AsyncSession) -> EmbeddingClustererState:
        errors: list[str] = []
        news_embedded, chunks_embedded = await self._embed_parallel(errors)

        # "당일 수집분" 창은 한 번만 계산해 dedup·클러스터링에 같은 값을 넘긴다 —
        # 단계 간 처리 범위가 어긋나면 dedup 안 된 행이 클러스터에 섞인다.
        since = now_kst() - timedelta(hours=settings.pipeline_window_hours)
        duplicates_removed = await flag_duplicates_by_similarity(
            db, settings.dedup_similarity_threshold, cutoff=since
        )
        clusters_formed, top_issues = await self._cluster_and_select(db, since)

        logger.info(
            "EmbeddingClusterer 완료 news_embedded=%d chunks_embedded=%d duplicates=%d "
            "clusters=%d top=%d errors=%d",
            news_embedded, chunks_embedded, duplicates_removed,
            clusters_formed, len(top_issues), len(errors),
        )
        return EmbeddingClustererState(
            news_embedded=news_embedded,
            chunks_embedded=chunks_embedded,
            duplicates_removed=duplicates_removed,
            clusters_formed=clusters_formed,
            top_issues=top_issues,
            errors=errors,
        )

    async def _embed_parallel(self, errors: list[str]) -> tuple[int, int]:
        """두 임베딩을 독립 세션에서 병렬 실행한다. 한쪽 실패는 errors에 담고 0으로 처리한다."""
        news_result, chunks_result = await asyncio.gather(
            self._embed_news(), self._embed_chunks(), return_exceptions=True
        )
        news_embedded = self._unwrap(news_result, "embed_news", errors)
        chunks_embedded = self._unwrap(chunks_result, "embed_chunks", errors)
        return news_embedded, chunks_embedded

    async def _embed_news(self) -> int:
        async with AsyncSessionLocal() as session:
            return await self.news_embedder.embed_news(session)

    async def _embed_chunks(self) -> int:
        async with AsyncSessionLocal() as session:
            return await self.report_embedder.embed_chunks(session)

    @staticmethod
    def _unwrap(result: int | BaseException, label: str, errors: list[str]) -> int:
        """gather 결과를 푼다 — 예외면 errors에 기록하고 0(부분 실패 후 나머지 단계는 진행)."""
        if isinstance(result, BaseException):
            logger.warning("%s 실패: %s", label, result)
            errors.append(f"{label}: {result}")
            return 0
        return result

    async def _cluster_and_select(self, db: AsyncSession, since: datetime) -> tuple[int, list[int]]:
        """클러스터링 → 싱글톤 보존 → 중심 근접순 정렬 → 중요도 스코어 → news_cluster 적재.

        since: 수집 시각 하한(run()이 dedup과 공유하는 창) — 경계가 없으면 백로그 전체가
        매일 재클러스터링된다.
        """
        rows = await get_clusterable_news(db, since)
        if len(rows) < settings.cluster_min_cluster_size:
            # 표본이 최소 클러스터 크기보다 작으면 묶을 게 없다 — 빈 결과로 종료(멱등).
            return 0, []

        news_ids = [row.id for row in rows]
        embeddings = np.array([row.embedding for row in rows], dtype=np.float32)

        labels = cluster_news(
            embeddings,
            min_cluster_size=settings.cluster_min_cluster_size,
            min_samples=settings.cluster_min_samples,
        )
        labels = promote_singletons(labels)  # noise(-1)도 size-1 클러스터로 보존

        scored = self._score_clusters(labels, news_ids, embeddings)
        top_issues = await persist_clusters(db, now_kst().date(), scored)
        return len(scored), top_issues

    @staticmethod
    def _score_clusters(
        labels: np.ndarray, news_ids: list[int], embeddings: np.ndarray
    ) -> list[ClusterScore]:
        """각 클러스터를 중심 근접순 정렬 후 복합 중요도로 스코어링한다.

        Sentiment·Entity·prev_cluster_size는 상류·이력이 아직 없어 0이다.
        """
        # 클러스터별 소속 행 인덱스 — 크기(sizes)는 len(positions)로 유도되므로 따로 두지 않는다.
        cluster_positions = [
            np.where(labels == label)[0].tolist() for label in np.unique(labels)
        ]
        max_size = max((len(p) for p in cluster_positions), default=1)

        scored: list[ClusterScore] = []
        for positions in cluster_positions:
            ordered = order_by_centrality(positions, embeddings)  # 중심 근접순 행 인덱스
            scored.append(
                ClusterScore(
                    member_news_ids=[news_ids[p] for p in ordered],
                    importance=score_cluster(
                        cluster_size=len(positions), max_cluster_size=max_size
                    ),
                )
            )
        return scored
