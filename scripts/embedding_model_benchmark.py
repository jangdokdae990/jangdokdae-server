"""임베딩 모델 비교 하니스 — 후보 모델을 동일 라벨셋으로 끝까지 돌려 결과표 한 장으로 비교.

cosine 분리도만 보지 말고 클러스터링(ARI·Silhouette)·RAG(recall@5)까지 같은 조건으로 측정한다.

지표:
    - pair_auc   : 같은이슈 쌍 vs 다른이슈 쌍 cosine을 AUC로(임계값 무관 단일 분리도 수치)
    - ari        : 동일 HDBSCAN 설정 결과를 사람 정답(gold_labels)과 비교한 Adjusted Rand Index
    - silhouette : 클러스터 응집도(noise 제외, cosine)
    - rag_recall : (선택) 쿼리별 similarity_search top-5에 정답 청크가 든 비율

사용:
    python -m scripts.embedding_model_benchmark [labelset.json]
    # 라벨셋 기본 경로: scripts/data/embedding_labelset.json
    # 형식은 scripts/data/embedding_labelset.example.json 참고 (실데이터로 채워야 함)
"""

import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import adjusted_rand_score, roc_auc_score
from sklearn.metrics.pairwise import cosine_similarity

from services.embedder.cluster import cluster_news, evaluate_clustering
from services.embedder.embedding_client import EmbeddingClient, embed_with

# 비교 대상 — 관리형 1 + 오픈소스 2(baseline 포함).
CANDIDATE_MODELS = [
    "gemini-embedding-001",         # Vertex AI, 768 절단, MTEB Multilingual 1위 (관리형 후보)
    "gemini-embedding-2-preview",   # 후속 v2(genai, 8192토큰), us-central1 전용 — 001과 비교
    "nlpai-lab/KURE-v1",            # 한국어 검색 특화, MTEB-ko 1위 (1024)
    "jhgan/ko-sroberta-multitask",  # 현재 코드 기본값 — baseline
]

DEFAULT_LABELSET = Path("scripts/data/embedding_labelset.json")
EXAMPLE_LABELSET = Path("scripts/data/embedding_labelset.example.json")
RAG_TOP_K = 5


def _pair_sims(sim_matrix: np.ndarray, pairs: list[list[int]]) -> list[float]:
    """인덱스 쌍 목록의 cosine 유사도를 뽑아낸다."""
    return [float(sim_matrix[i, j]) for i, j in pairs]


def rag_recall_at_k(model_name: str, rag: dict, k: int = RAG_TOP_K) -> float | None:
    """RAG 검색 품질 — 쿼리별 top-k에 정답 청크가 든 비율의 평균.

    chunks는 RETRIEVAL_DOCUMENT, query는 RETRIEVAL_QUERY task type으로 임베딩한다.
    rag 데이터가 없으면 None을 반환해 표에서 'n/a'로 표시한다.
    """
    chunks = rag.get("chunks") or []
    queries = rag.get("queries") or []
    if not chunks or not queries:
        return None

    client = EmbeddingClient(model_name=model_name)
    chunk_matrix = client.embed_matrix(chunks, task_type="RETRIEVAL_DOCUMENT")

    recalls: list[float] = []
    for q in queries:
        relevant = set(q["relevant_chunk_ids"])
        if not relevant:
            continue
        q_vec = client.embed_matrix([q["query"]], task_type="RETRIEVAL_QUERY")
        sims = cosine_similarity(q_vec, chunk_matrix)[0]
        top_k = set(np.argsort(sims)[::-1][:k].tolist())
        recalls.append(len(top_k & relevant) / len(relevant))
    return float(np.mean(recalls)) if recalls else None


def benchmark(model_name: str, labelset: dict) -> dict:
    """모델 하나를 라벨셋 전체로 평가해 지표 dict를 반환한다."""
    news_texts: list[str] = labelset["news_texts"]
    pos_pairs: list[list[int]] = labelset["pos_pairs"]
    neg_pairs: list[list[int]] = labelset["neg_pairs"]
    gold_labels = np.array(labelset["gold_labels"])

    embeddings = embed_with(model_name, news_texts, task_type="CLUSTERING")
    sim_matrix = cosine_similarity(embeddings)

    # ① 분리도: 같은이슈 쌍 vs 다른이슈 쌍 cosine을 AUC로(임계값 무관 단일 수치)
    pos = _pair_sims(sim_matrix, pos_pairs)
    neg = _pair_sims(sim_matrix, neg_pairs)
    pair_auc = float(roc_auc_score([1] * len(pos) + [0] * len(neg), pos + neg))

    # ② 클러스터링: 동일 HDBSCAN 설정으로 돌려 사람 정답과 ARI 비교
    labels = cluster_news(embeddings, min_cluster_size=2, min_samples=1)
    ari = float(adjusted_rand_score(gold_labels, labels))
    silhouette = evaluate_clustering(embeddings, labels)["silhouette"]

    return {
        "model": model_name,
        "pair_auc": pair_auc,
        "ari": ari,
        "silhouette": silhouette,
        "pos_mean": float(np.mean(pos)) if pos else None,
        "neg_mean": float(np.mean(neg)) if neg else None,
        "rag_recall": rag_recall_at_k(model_name, labelset.get("rag", {})),
    }


def _fmt(value: float | None) -> str:
    return f"{value:.3f}" if value is not None else "  n/a"


def print_results(results: list[dict]) -> None:
    """결과표를 정렬해 출력한다."""
    header = f"{'model':<30}{'pair_auc':>10}{'ari':>8}{'silhouette':>12}{'pos/neg':>16}{'rag@5':>8}"
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: (x["pair_auc"], x["ari"]), reverse=True):
        pos_neg = f"{_fmt(r['pos_mean'])}/{_fmt(r['neg_mean'])}"
        print(
            f"{r['model']:<30}{_fmt(r['pair_auc']):>10}{_fmt(r['ari']):>8}"
            f"{_fmt(r['silhouette']):>12}{pos_neg:>16}{_fmt(r['rag_recall']):>8}"
        )


def load_labelset(path: Path) -> dict:
    """라벨셋 JSON을 로드한다. 없으면 형식 안내와 함께 종료한다."""
    if not path.exists():
        print(f"라벨셋이 없습니다: {path}")
        print(f"→ {EXAMPLE_LABELSET} 형식을 참고해 실제 수집 뉴스로 채운 뒤 다시 실행하세요.")
        print("  필수 키: news_texts, pos_pairs, neg_pairs, gold_labels (rag는 선택)")
        sys.exit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def main(labelset_path: Path) -> None:
    labelset = load_labelset(labelset_path)
    print(f"라벨셋: {labelset_path} (뉴스 {len(labelset['news_texts'])}건)\n")
    results = [benchmark(model, labelset) for model in CANDIDATE_MODELS]
    print_results(results)


if __name__ == "__main__":
    arg_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LABELSET
    main(arg_path)
