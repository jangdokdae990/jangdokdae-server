"""NewsCollector — 뉴스 수집 단계 조립 (collect → preprocess → save).

설계 02 §7.2. RSS 폴링(rss_collector) → 인메모리 전처리(news_preprocessor) →
정제본 1회 저장(save_tool.upsert_news)의 **정적 순차**다. 분기·반복·LLM 추론이 없어
Airflow Task로 실행된다. 클러스터링·스코어링은 후속 단계(EmbeddingClusterer, →05)가 맡는다.

저장된 정제 뉴스(탈락분은 is_filtered=True)는 단계끼리 직접 호출하지 않고
EmbeddingClusterer가 `is_filtered = FALSE AND embedding IS NULL`로 이어받는다(→01 §2).
"""

import logging
from typing import TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from services.collector.rss_collector import RSSCollector
from services.collector.tools.save_tool import upsert_news
from services.preprocessor.news_preprocessor import run_preprocessing

logger = logging.getLogger(__name__)


class NewsCollectorState(TypedDict):
    """단계 실행 결과 요약 — Airflow XCom·러너가 읽는 단계 간 보고 형식.

    데이터 자체(레코드)가 아니라 카운트와 실패 신호만 담는다. 실제 데이터 핸드오프는
    공유 DB의 상태 컬럼(is_filtered/embedding)으로 이뤄지므로(설계 01 §2), 반환값에
    레코드를 실으면 XCom이 비대해지고 DB 핸드오프 원칙과 어긋난다.
    """

    schedule: str            # 실행 트리거 식별자 (예: "morning" / "afternoon")
    collected: int           # RSS에서 수집한 원시 기사 수
    kept: int                # 전처리 통과(분석 대상) 수 — is_filtered=False
    saved: int               # upsert_news가 새로 삽입한 수 (url 중복은 DO NOTHING)
    failed_feeds: list[str]  # 수집 실패한 피드 식별자 — 부분 실패 가시성(빈 리스트=전부 성공)


class NewsCollector:
    """collect → preprocess → save 정적 순차를 조립하는 수집 단계."""

    def __init__(self, rss_collector: RSSCollector | None = None) -> None:
        self.rss_collector = rss_collector or RSSCollector()

    async def run(self, db: AsyncSession, schedule: str) -> NewsCollectorState:
        collected, failed_feeds = await self.rss_collector.collect()
        # 전처리는 별도 단계가 아니라 수집 노드 안의 인메모리 모듈 — 외부 의존성이 없어
        # DB 핸드오프가 불필요하다(→04 §1.2). 탈락분도 is_filtered=True로 함께 반환된다.
        records, stats = run_preprocessing([item.to_record() for item in collected])
        saved = await upsert_news(db, records)
        logger.info(
            "NewsCollector 완료 schedule=%s collected=%d kept=%d saved=%d failed_feeds=%d",
            schedule,
            len(collected),
            stats.kept,
            saved,
            len(failed_feeds),
        )
        if failed_feeds:
            # 부분 실패는 Task 성공으로 끝나므로 경고로 끌어올려 수집량 급감을 놓치지 않는다.
            logger.warning("일부 RSS 피드 수집 실패 schedule=%s feeds=%s", schedule, failed_feeds)
        return NewsCollectorState(
            schedule=schedule,
            collected=len(collected),
            kept=stats.kept,
            saved=saved,
            failed_feeds=failed_feeds,
        )
