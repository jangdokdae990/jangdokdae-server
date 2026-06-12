"""뉴스 클러스터링 — HDBSCAN으로 같은 이슈 기사를 묶는다(설계 05 §5).

채택 근거(05 §5.2): 오늘 주요 이슈가 몇 개인지 알 수 없어 클러스터 수 사전 지정이 불가능하고,
밀도가 제각각인 이슈(금리 결정 50건 vs 단독 보도 2건)를 한 번에 처리해야 하므로 K-Means·임계값
그룹핑이 아니라 HDBSCAN을 쓴다. min_cluster_size 하나로 나머지는 데이터가 결정한다.

cluster_news/evaluate_clustering는 비교 하니스(05 §11)도 공유한다. 싱글톤 보존
(promote_singletons)·중심 근접순 정렬(order_by_centrality)까지 이 모듈이 맡고, 중요도
스코어링·news_cluster 적재는 score 모듈(05 §6)이 이 위에 쌓는다.
"""

import logging

import hdbscan
import numpy as np
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

DEFAULT_MIN_CLUSTER_SIZE = 2  # 같은 이슈를 2개 이상 언론사가 보도하면 클러스터 형성(05 §5.6)
DEFAULT_MIN_SAMPLES = 1       # 가장 공격적(noise 최소) — 싱글톤 보존 정책과 정합(05 §5.4)


def cluster_news(
    embeddings: np.ndarray,
    min_cluster_size: int = DEFAULT_MIN_CLUSTER_SIZE,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> np.ndarray:
    """HDBSCAN으로 뉴스 임베딩을 클러스터링한다. 반환: 기사별 클러스터 레이블(-1=noise).

    cosine distance(1 - cosine_similarity)를 precomputed로 넘긴다. 부동소수 오차로 거리가
    음수가 되면 HDBSCAN precomputed가 거부하므로 0 하한으로 클리핑한다.
    """
    if len(embeddings) < min_cluster_size:
        # 표본이 최소 클러스터 크기보다 작으면 묶을 수 없다 — 전부 noise로 본다.
        return np.full(len(embeddings), -1, dtype=int)

    distance_matrix = np.clip(1.0 - cosine_similarity(embeddings), 0.0, None).astype(np.float64)
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=min_cluster_size,
        min_samples=min_samples,
        metric="precomputed",
        cluster_selection_method="eom",  # excess of mass — 자연스러운 클러스터 선택(05 §5.2)
    )
    labels: np.ndarray = clusterer.fit_predict(distance_matrix)
    return labels


def evaluate_clustering(
    embeddings: np.ndarray,
    labels: np.ndarray,
) -> dict[str, float | int | None]:
    """클러스터링 자동 지표(설계 05 §5.5). noise(-1)는 품질 지표 계산에서 제외한다.

    Silhouette/Davies-Bouldin은 noise 제외 후 클러스터가 2개 이상이어야 정의된다 —
    그 조건을 못 채우면 None을 반환하고 호출부가 판단 보류하도록 한다.
    """
    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    noise_ratio = float((labels == -1).sum() / len(labels)) if len(labels) else 0.0

    mask = labels != -1
    # silhouette은 표본 ≥2 + 서로 다른 클러스터 ≥2가 있어야 계산 가능.
    if mask.sum() < 2 or len(set(labels[mask].tolist())) < 2:
        return {
            "silhouette": None,
            "davies_bouldin": None,
            "n_clusters": n_clusters,
            "noise_ratio": noise_ratio,
        }

    return {
        # Silhouette: -1~1, 높을수록 좋음. 금융 뉴스는 0.2~0.35도 현실적(05 §5.3).
        "silhouette": float(silhouette_score(embeddings[mask], labels[mask], metric="cosine")),
        # Davies-Bouldin: 낮을수록 좋음.
        "davies_bouldin": float(davies_bouldin_score(embeddings[mask], labels[mask])),
        "n_clusters": n_clusters,
        "noise_ratio": noise_ratio,
    }


def promote_singletons(labels: np.ndarray) -> np.ndarray:
    """noise(-1)를 각각 size-1 클러스터로 승격한다(설계 05 §5.4).

    코퍼스가 이미 2중 정제(증권 RSS 도메인 + FilterChain 통과)됐으므로 noise는 "주제 무관"이
    아니라 "오늘 단독 보도된 기사"다 — 잠재 고가치라 버리지 않는다. 모든 기사를 클러스터에 넣어
    동일 기준으로 importance를 경쟁시키고(§6), 우선순위는 TOP_ISSUE_COUNT 컷오프가 정한다.
    """
    out = labels.copy()
    next_id = int(labels.max()) + 1 if len(labels) else 0
    for i in np.where(labels == -1)[0]:
        out[i] = next_id
        next_id += 1
    return out


def order_by_centrality(cluster_ids: list[int], embeddings: np.ndarray) -> list[int]:
    """클러스터 중심에 가까운 순으로 기사 위치(행 인덱스)를 정렬한다(설계 05 §5.8).

    인자 cluster_ids는 embeddings 행렬의 행 인덱스다. 반환 [0]=대표기사, 이후=본문 fetch
    fallback·다관점 후보 순서. 대표를 1건만 두되 fetch 실패 시 다음 후보로 내려가도록
    member_news_ids를 이 순서로 저장한다(02 §8.4).
    """
    cluster_embeddings = embeddings[cluster_ids]
    centroid = cluster_embeddings.mean(axis=0)
    sims = cosine_similarity([centroid], cluster_embeddings)[0]
    order = np.argsort(sims)[::-1]  # 유사도 내림차순 — 중심에 가까운 기사가 앞
    return [cluster_ids[i] for i in order]
