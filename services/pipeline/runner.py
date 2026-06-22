"""하이브리드 로컬 실행용 러너 — Airflow 없이 전체 파이프라인을 1회 완주한다.

운영 오케스트레이션은 Airflow DAG가 전담하고, 이 러너는 로컬·테스트 편의만 맡는 얇은 함수다.
단계 간 데이터는 공유 DB 상태 핸드오프라 러너든 DAG든 동작은 동일하다.

흐름: (NewsCollector ∥ CompanyCollector) → EmbeddingClusterer → NewsAnalyzer(분류·콘텐츠, →10).
전처리는 별도 단계가 아니라 NewsCollector 안의 인메모리 모듈이다(설계 04 §1.2).

사용:
    python -m services.pipeline.runner            # schedule="morning"
    python -m services.pipeline.runner afternoon  # 오후 실행분
"""

import asyncio
import logging
import sys

from app.db.base import AsyncSessionLocal
from services.pipeline.company_collector import CompanyCollector
from services.pipeline.embedding_clusterer import EmbeddingClusterer, EmbeddingClustererState
from services.pipeline.news_analyzer import NewsAnalyzer, NewsAnalyzerState
from services.pipeline.news_collector import NewsCollector, NewsCollectorState

logger = logging.getLogger(__name__)

DEFAULT_SCHEDULE = "morning"  # CompanyCollector 정적 분기와 호환되는 일일 스케줄


async def _run_news_collector(schedule: str) -> NewsCollectorState:
    # AsyncSession은 동시 사용이 안전하지 않으므로 병렬 단계마다 독립 세션을 연다.
    async with AsyncSessionLocal() as db:
        return await NewsCollector().run(db, schedule)


async def run_pipeline(schedule: str = DEFAULT_SCHEDULE) -> dict[str, object]:
    """수집(병렬) → 임베딩·클러스터링 → 분석. 1회 호출 = 전체 파이프라인 완주.

    수집 한쪽이 실패하면 전체가 중단된다 — 로컬·테스트 도구라 부분 실패를 숨기기보다
    즉시 드러내는 쪽이 낫다(운영의 Task별 격리·재시도는 Airflow가 담당).
    """
    news_state, company_state = await asyncio.gather(
        _run_news_collector(schedule),
        CompanyCollector().run(schedule),
    )

    async with AsyncSessionLocal() as db:
        embed_state: EmbeddingClustererState = await EmbeddingClusterer().run(db)

    # 분석(분류·콘텐츠 생성, →10) — embed_state가 적재한 news_cluster를 DB로 이어받는다.
    async with AsyncSessionLocal() as db:
        analyze_state: NewsAnalyzerState = await NewsAnalyzer().run(db)

    logger.info(
        "run_pipeline 완료 schedule=%s news=%s company=%s embed=%s analyze=%s",
        schedule, news_state, company_state, embed_state, analyze_state,
    )
    return {
        "news": news_state,
        "company": company_state,
        "embedding": embed_state,
        "analyze": analyze_state,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    asyncio.run(run_pipeline(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_SCHEDULE))
