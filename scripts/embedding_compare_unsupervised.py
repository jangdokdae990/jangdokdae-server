"""임베딩 모델 비지도 비교 — 실제 수집 뉴스로 라벨 없이 모델별 클러스터링 품질을 본다.

라벨이 아직 없을 때 실제 뉴스 제목으로 후보 모델을 각각 클러스터링해
silhouette·클러스터 수·noise 비율과 샘플 클러스터를 나란히 찍어 눈으로 품질을 비교한다.

주의(해석):
    - silhouette은 각 모델의 자기 임베딩 공간에서 계산되므로 모델 간 절대 비교는 약하다.
      진짜 신호는 "같은 이슈 기사가 한 클러스터에 잘 묶이는가"를 샘플 클러스터로 눈으로 보는 것.

사용:
    python -m scripts.embedding_compare_unsupervised [n_titles]   # 기본 300건
    # gemini는 Vertex 인증 필요: 먼저 `gcloud auth application-default login`
"""

import asyncio
import sys

import numpy as np
from sqlalchemy import text

from app.db.base import AsyncSessionLocal
from services.embedder.cluster import cluster_news, evaluate_clustering
from services.embedder.embedding_client import embed_with

# 비교 대상 — 관리형 1 + 오픈소스 2.
CANDIDATE_MODELS = [
    "gemini-embedding-001",         # Vertex AI, 768 절단 (인증 필요)
    "nlpai-lab/KURE-v1",            # 한국어 검색 특화, 1024
    "jhgan/ko-sroberta-multitask",  # baseline, 768
]

DEFAULT_N_TITLES = 300
SAMPLE_CLUSTERS = 6   # 출력할 샘플 클러스터 수(큰 것부터)
SAMPLE_TITLES = 5     # 클러스터당 출력할 제목 수


async def fetch_titles(n: int) -> list[str]:
    """분석 대상(is_filtered=false) 뉴스 제목을 최신순으로 n건 가져온다."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(
                "SELECT title FROM news WHERE is_filtered = false "
                "ORDER BY published_at DESC NULLS LAST LIMIT :n"
            ),
            {"n": n},
        )
        return [row[0] for row in result]


def show_sample_clusters(titles: list[str], labels: np.ndarray) -> None:
    """큰 클러스터부터 SAMPLE_CLUSTERS개, 각 SAMPLE_TITLES건씩 제목을 출력한다."""
    clusters: dict[int, list[str]] = {}
    for title, label in zip(titles, labels.tolist()):
        if label == -1:  # noise(싱글톤)는 샘플에서 제외 — 묶임 품질이 관심사
            continue
        clusters.setdefault(label, []).append(title)

    for label, members in sorted(clusters.items(), key=lambda kv: len(kv[1]), reverse=True)[
        :SAMPLE_CLUSTERS
    ]:
        print(f"    [클러스터 {label}] {len(members)}건")
        for title in members[:SAMPLE_TITLES]:
            print(f"      · {title}")
        if len(members) > SAMPLE_TITLES:
            print(f"      … 외 {len(members) - SAMPLE_TITLES}건")


def compare_model(model_name: str, titles: list[str]) -> dict | None:
    """모델 하나로 임베딩→클러스터링→지표. 실패(인증·다운로드)는 None 반환 후 사유 출력."""
    print(f"\n■ {model_name}")
    try:
        embeddings = embed_with(model_name, titles, task_type="CLUSTERING")
    except Exception as e:  # 인증 만료·모델 다운로드 실패 등 — 한 모델 실패가 전체를 막지 않게
        print(f"    SKIP — 임베딩 실패: {type(e).__name__}: {str(e)[:200]}")
        return None

    labels = cluster_news(embeddings, min_cluster_size=2, min_samples=1)
    metrics = evaluate_clustering(embeddings, labels)
    sil = metrics["silhouette"]
    sil_str = f"{sil:.3f}" if sil is not None else "n/a"
    print(
        f"    dim={embeddings.shape[1]}  clusters={metrics['n_clusters']}  "
        f"noise={metrics['noise_ratio']:.1%}  silhouette={sil_str}"
    )
    show_sample_clusters(titles, labels)
    return {"model": model_name, **metrics, "dim": int(embeddings.shape[1])}


def print_summary(results: list[dict]) -> None:
    print("\n=== 요약 (silhouette은 모델 간 약한 비교 — 샘플 클러스터를 같이 보세요) ===")
    header = f"{'model':<30}{'dim':>6}{'clusters':>10}{'noise':>8}{'silhouette':>12}"
    print(header)
    print("-" * len(header))
    for r in results:
        sil = f"{r['silhouette']:.3f}" if r["silhouette"] is not None else "n/a"
        print(
            f"{r['model']:<30}{r['dim']:>6}{r['n_clusters']:>10}"
            f"{r['noise_ratio']:>7.1%}{sil:>12}"
        )


def main(n_titles: int) -> None:
    titles = asyncio.run(fetch_titles(n_titles))
    print(f"분석 대상 제목 {len(titles)}건으로 {len(CANDIDATE_MODELS)}개 모델 비교\n")
    if len(titles) < 2:
        print("제목이 너무 적어 클러스터링 불가 — 뉴스 수집 후 다시 실행하세요.")
        return

    results = [compare_model(m, titles) for m in CANDIDATE_MODELS]
    ok = [r for r in results if r is not None]
    if ok:
        print_summary(ok)
    else:
        print("\n실행된 모델이 없습니다.")
        print("gemini는 `gcloud auth application-default login` 으로 재인증 후 다시 실행하세요.")


if __name__ == "__main__":
    arg_n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N_TITLES
    main(arg_n)
