"""클러스터링 알고리즘 어댑터 — Gate 2(알고리즘 선정)용 HDBSCAN vs 그래프.

HDBSCAN은 기존 운영 코드(`services/embedder.cluster.cluster_news`)를 재사용한다(여기선 import만).
그래프 알고리즘은 cosine 임계 그래프의 **연결요소**를 클러스터로 보고, 너무 큰 요소는
임계를 올려 **재귀 분할**한다(설계 05 §5.1~5.2).
"""

from __future__ import annotations

import networkx as nx  # type: ignore[import-untyped]
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity


def graph_cluster(
    embeddings: np.ndarray,
    *,
    threshold: float = 0.7,
    max_size: int = 20,
    step: float = 0.05,
    cap: float = 0.95,
) -> np.ndarray:
    """cosine 임계 그래프의 연결요소로 클러스터링하고, 큰 요소는 임계를 올려 재귀 분할한다.

    반환: 기사별 클러스터 레이블(연속 정수). 고립 노드는 자연히 단독 클러스터가 된다(noise 없음).
    threshold=연결 임계, max_size 초과 요소는 step씩 올려 cap까지 재분할.
    """
    n = len(embeddings)
    sim = cosine_similarity(embeddings)
    labels = np.full(n, -1, dtype=int)
    next_id = 0

    def components(idx: list[int], thr: float) -> list[list[int]]:
        graph: nx.Graph = nx.Graph()
        graph.add_nodes_from(idx)
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                if sim[idx[a], idx[b]] >= thr:
                    graph.add_edge(idx[a], idx[b])
        return [list(c) for c in nx.connected_components(graph)]

    def recurse(idx: list[int], thr: float) -> None:
        nonlocal next_id
        for comp in components(idx, thr):
            if len(comp) <= max_size or thr >= cap:
                for i in comp:
                    labels[i] = next_id
                next_id += 1
            else:
                recurse(comp, min(thr + step, cap))

    recurse(list(range(n)), threshold)
    return labels
