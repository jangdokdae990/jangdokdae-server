"""유사도 기반 근접 중복 표시 — 임베딩 후 거의 동일한 기사를 soft flag한다(설계 05 §4.2).

전처리(04)의 제목 Jaccard 중복 제거는 같은 실행 내 한정이라, 런 간·통신사 받아쓰기 중복은
임베딩 유사도(cosine ≥ 0.95)로 여기서 잡는다. **삭제하지 않고 is_duplicate=TRUE로 표시**한다
— 행을 보존해 ① news_cluster FK 정합성, ② URL 멱등 재수집 방지(재임베딩 비용), ③ "무엇이
중복으로 빠졌는지" 추적을 모두 지킨다(05 §4.2). 클러스터링·분석은 is_duplicate=FALSE만 읽는다.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from utils.dates import now_kst

logger = logging.getLogger(__name__)

# 같은 근접 중복 쌍에서 발행 시각(없으면 수집 시각)이 늦은 쪽을 중복으로 표시하고, 이른 쪽을
# 대표로 남긴다(설계 05 §4.2 — "published_at이 늦은 것을 표시"). RSS는 발행순 전달이 보장되지
# 않아 id 순서는 발행 순서와 어긋날 수 있으므로 쓰지 않는다. published_at은 nullable이라
# created_at 폴백 + id 타이브레이크로 전순서를 보장한다(행값 비교는 사전식).
# pgvector `<=>`는 cosine distance이므로 유사도 = 1 - distance.
# :cutoff는 KST naive 하한 — created_at이 KST naive라 SQL NOW()(UTC)와 직접 비교하면
# 9시간 어긋나므로(33h 창) 파이썬에서 같은 기준(KST)으로 계산해 넘긴다.
_FLAG_DUPLICATES_SQL = text(
    """
    UPDATE news SET is_duplicate = TRUE
    WHERE id IN (
        SELECT n2.id
        FROM news n1
        JOIN news n2
          ON (COALESCE(n1.published_at, n1.created_at), n1.id)
           < (COALESCE(n2.published_at, n2.created_at), n2.id)
        WHERE n1.embedding IS NOT NULL
          AND n2.embedding IS NOT NULL
          AND n1.is_filtered = FALSE
          AND n2.is_filtered = FALSE
          AND n1.is_duplicate = FALSE
          AND n2.is_duplicate = FALSE
          AND (1 - (n1.embedding <=> n2.embedding)) >= :threshold
          AND n1.created_at >= :cutoff
          AND n2.created_at >= :cutoff
    )
    """
)


async def flag_duplicates_by_similarity(
    db: AsyncSession,
    threshold: float = 0.95,
    cutoff: datetime | None = None,
) -> int:
    """임베딩 유사도 기반 근접 중복을 is_duplicate=TRUE로 표시하고 표시 건수를 반환한다.

    당일 수집분 대상 — cutoff 미지정 시 공용 파이프라인 창(settings.pipeline_window_hours)으로
    계산한다. 파이프라인에서는 단계 간 창 일치를 위해 호출부(EmbeddingClusterer)가 한 번 계산해
    명시 전달한다. 같은 플래그를 다시 세팅할 뿐이라 재실행해도 멱등하다(설계 05 §4.2).
    """
    if cutoff is None:
        cutoff = now_kst() - timedelta(hours=settings.pipeline_window_hours)
    result = await db.execute(_FLAG_DUPLICATES_SQL, {"threshold": threshold, "cutoff": cutoff})
    await db.commit()
    flagged = int(result.rowcount)  # type: ignore[attr-defined]
    logger.info("근접 중복 표시 count=%d threshold=%.2f cutoff=%s", flagged, threshold, cutoff)
    return flagged
