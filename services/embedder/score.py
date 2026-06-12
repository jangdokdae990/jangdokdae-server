"""복합 중요도 스코어 — 클러스터를 평가해 오늘의 주요 이슈를 선정한다(설계 05 §6).

클러스터(같은 이슈 기사 그룹) 단위 평가라 임베딩·클러스터링이 끝난 뒤에야 가능하다. 각 신호를
[0,1]로 정규화해 가중합한다 — 스케일이 다른 raw 값(volume 50, velocity 1.2)을 그대로 더하면
한 신호가 지배하므로 정규화가 필수다.

> 가중치 W는 **학술 단일 출처가 없는 휴리스틱 초기값**이다(05 §6.0·§11). "볼륨·속도가 유효"의
> 근거는 벤치마크(카카오 RUBICS=볼륨, Bloomberg=속도)에서 왔고, 가중치 자체는 실데이터 교정
> 대상이다. Sentiment·Entity는 MVP 신호로 공식에 포함하되 상류 단계가 값을 채우기 전엔 0이다.
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from services.collector.tools.save_tool import upsert_news_clusters

logger = logging.getLogger(__name__)

# 신호별 가중치 — 휴리스틱 초기값(교정 전, 학술 단일 출처 없음 → 05 §6.0·§11).
W = {"volume": 0.4, "velocity": 0.3, "sentiment": 0.15, "entity": 0.15}


@dataclass
class ClusterScore:
    member_news_ids: list[int]  # 클러스터 소속 기사 id (중심 근접순 정렬 → 05 §5.8)
    importance: float           # 복합 중요도 [0,1]

    @property
    def representative_news_id(self) -> int:
        """대표 기사 = 중심 근접순 첫 번째(05 §5.8) — 파생값이라 저장하지 않고 유도한다."""
        return self.member_news_ids[0]


def score_cluster(
    cluster_size: int,
    max_cluster_size: int,
    prev_cluster_size: int = 0,
    sentiment_intensity: float = 0.0,
    entity_prominence: float = 0.0,
) -> float:
    """클러스터의 복합 중요도 [0,1]를 계산한다(설계 05 §6.1).

    - volume: 클러스터 크기를 당일 최대 크기로 정규화.
    - velocity: 이전 대비 증가율 [0,1] 클리핑. 이전 관측이 없으면(prev=0) 베이스라인이 없어
      속도를 잴 수 없으므로 0이다 — 설계 §6.1 본문의 의도("첫 실행 prev=0 → 0")를 따른다.
      (같은 절의 예시 식 (size-prev)/(prev+1)은 prev=0에서 size를 그대로 키워 모든 클러스터를
      velocity_n=1로 만드는 결함이 있어, 신호 변별을 위해 prev=0을 0으로 처리한다 → §11.)
    - sentiment_intensity·entity_prominence: 상류 단계가 채우기 전엔 0(MVP, → 05 §11).
    """
    volume_n = cluster_size / max(max_cluster_size, 1)
    if prev_cluster_size <= 0:
        velocity_n = 0.0
    else:
        velocity_n = max(0.0, min((cluster_size - prev_cluster_size) / prev_cluster_size, 1.0))
    return (
        W["volume"] * volume_n
        + W["velocity"] * velocity_n
        + W["sentiment"] * sentiment_intensity
        + W["entity"] * entity_prominence
    )


async def persist_clusters(
    db: AsyncSession,
    run_date: date,
    scored_clusters: list[ClusterScore],
) -> list[int]:
    """클러스터를 news_cluster에 적재하고 importance 상위 N개 대표 기사 id를 반환한다(05 §6.2).

    (run_date, representative_news_id) 기준 UPSERT — 재실행·오후 런은 같은 클러스터의
    소속·중요도를 갱신할 뿐 중복 적재하지 않는다(재실행 멱등, 설계 01 §2). embedding은
    기사당 값이라 news에 남고, 여기엔 클러스터 식별·소속·중요도만 적재한다.
    분석 단계는 반환된 상위 대표 id를 인계받아 Issue Docent를 생성한다.
    """
    if not scored_clusters:
        return []
    top_n = settings.top_issue_count
    affected = await upsert_news_clusters(
        db,
        [
            {
                "run_date": run_date,
                "representative_news_id": cluster.representative_news_id,
                "member_news_ids": cluster.member_news_ids,
                "size": len(cluster.member_news_ids),
                "importance": cluster.importance,
            }
            for cluster in scored_clusters
        ],
    )

    top = sorted(scored_clusters, key=lambda c: c.importance, reverse=True)[:top_n]
    logger.info(
        "클러스터 적재 count=%d affected=%d top=%d", len(scored_clusters), affected, len(top)
    )
    return [c.representative_news_id for c in top]
