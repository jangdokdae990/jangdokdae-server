# 단독 실행: uv run pytest tests/test_embedder.py -s
"""embedder 순수 함수 단위 테스트 — 싱글톤 보존·중심 정렬·복합 중요도 스코어(설계 05 §5·§6).

DB·외부 API 없이 검증 가능한 순수 로직만 다룬다. 임베딩 호출·DB 적재는 통합 단계에서 검증한다.
"""

import numpy as np

from services.embedder.cluster import order_by_centrality, promote_singletons
from services.embedder.news_embedder import build_embed_text
from services.embedder.score import W, score_cluster
from services.pipeline.embedding_clusterer import EmbeddingClusterer


def test_build_embed_text_is_title_only():
    # 설계 05 §2.2 — 뉴스 임베딩 입력은 제목 단독.
    assert build_embed_text("삼성전자 3분기 영업이익 9.2조") == "삼성전자 3분기 영업이익 9.2조"


def test_promote_singletons_assigns_unique_ids_to_noise():
    labels = np.array([0, 0, -1, 1, -1])
    out = promote_singletons(labels)
    # noise(-1)는 사라지고, 기존 클러스터(0,1)는 보존된다.
    assert -1 not in out
    assert out[0] == 0 and out[1] == 0 and out[3] == 1
    # 두 싱글톤은 서로 다른 새 클러스터 id를 받는다(max+1, max+2).
    assert out[2] != out[4]
    assert {int(out[2]), int(out[4])} == {2, 3}


def test_promote_singletons_all_noise():
    labels = np.array([-1, -1, -1])
    out = promote_singletons(labels)
    assert sorted(out.tolist()) == [0, 1, 2]  # 전부 단독 클러스터로 승격


def test_order_by_centrality_puts_central_article_first():
    # 0번과 1번은 거의 같은 방향, 2번은 멀다 → 중심은 0·1 쪽. 2번이 마지막.
    embeddings = np.array(
        [[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]], dtype=np.float32
    )
    ordered = order_by_centrality([0, 1, 2], embeddings)
    assert ordered[-1] == 2
    assert set(ordered) == {0, 1, 2}  # 입력 위치를 보존, 순서만 바뀜


def test_score_cluster_volume_normalization():
    # 최대 크기 클러스터는 volume_n=1. 첫 실행(prev=0)·sentiment·entity=0 → importance=W[volume].
    assert score_cluster(cluster_size=10, max_cluster_size=10) == W["volume"]


def test_score_cluster_smaller_is_lower():
    big = score_cluster(cluster_size=10, max_cluster_size=10)
    small = score_cluster(cluster_size=2, max_cluster_size=10)
    assert small < big


def test_score_cluster_velocity_clipped_to_one():
    # 급증해도 velocity_n은 1로 클리핑 → importance ≤ volume + velocity 가중치 합.
    score = score_cluster(cluster_size=10, max_cluster_size=10, prev_cluster_size=1)
    assert score <= W["volume"] + W["velocity"] + 1e-9


def test_score_clusters_builds_representative_from_centroid():
    # label 0: 위치 0·1(중심), label 1: 위치 2(싱글톤). 대표는 중심 근접 [0].
    labels = np.array([0, 0, 1])
    news_ids = [101, 102, 103]
    embeddings = np.array([[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]], dtype=np.float32)
    scored = EmbeddingClusterer._score_clusters(labels, news_ids, embeddings)

    assert len(scored) == 2
    pair = next(s for s in scored if len(s.member_news_ids) == 2)
    singleton = next(s for s in scored if len(s.member_news_ids) == 1)
    # 크기 2 클러스터가 크기 1보다 importance 높다(volume 지배).
    assert pair.importance > singleton.importance
    assert pair.representative_news_id in (101, 102)
    assert sorted(pair.member_news_ids) == [101, 102]
    assert singleton.member_news_ids == [103]
