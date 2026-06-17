"""RAG 검색 품질 벤치마크 — 사업보고서 청크 검색에서 임베딩 모델을 비교한다.

report_chunks(섹션 단위)를 코퍼스로 두고, 사람이 라벨링한
쿼리(scripts/data/rag_queries.json)별로 정답 섹션이 상위 k에 드는지 본다.
코퍼스에 여러 기업의 동일 유형 섹션(원재료·재무건전성 등)이 분산자로 섞여 있어,
모델이 기업·주제를 함께 변별하는지가 핵심이다.

지표:
    - recall@1/3/5 : 쿼리별 top-k에 정답 청크가 든 비율의 평균
    - MRR          : 첫 정답 청크 순위의 역수 평균(순위 품질까지 반영)

청크는 RETRIEVAL_DOCUMENT, 쿼리는 RETRIEVAL_QUERY task type으로 임베딩한다.
Vertex 계열만 task type을 반영하고 HuggingFace는 무시한다.

주의 — 섹션 길이와 모델 컨텍스트:
    report_chunks는 섹션 통째라 일부는 수만 자다. 512토큰 모델(ko-sroberta·kf-deberta)은
    뒤가 잘리므로 긴 섹션에서 불리하다. 결과 해석 시 코퍼스 길이 통계와 함께 본다.

사용:
    python -m scripts.rag_recall_benchmark
    # gemini 포함하려면 .env GOOGLE_APPLICATION_CREDENTIALS 설정 필요
"""

import asyncio
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.orm_models.report_chunk import ReportChunk
from services.embedder.embedding_client import EmbeddingClient

# 비교 대상 — 관리형 1 + 한국어 검색/금융 특화 + base + baseline.
# bge-m3 ↔ nmixx-bge-m3를 함께 둬 "금융 도메인 적응" 효과를 같은 계열에서 분리해 본다.
CANDIDATE_MODELS = [
    "gemini-embedding-001",          # Vertex 관리형, 768, 긴 컨텍스트 (현 우승)
    "gemini-embedding-2-preview",    # 후속 v2(genai, 8192토큰), us-central1 전용 — 001과 비교
    "nlpai-lab/KURE-v1",             # 한국어 검색 SOTA, 1024
    "nmixx-fin/nmixx-bge-m3",        # 한국어 금융 도메인 적응 bge-m3, 1024
    "BAAI/bge-m3",                   # nmixx의 base — 금융 적응 효과 분리용, 1024
    "upskyy/kf-deberta-multitask",   # KF-DeBERTa 금융 특화, 768 (512토큰)
    "jhgan/ko-sroberta-multitask",   # 현재 기본값 baseline, 768 (512토큰)
]

QUERIES_PATH = Path("scripts/data/rag_queries.json")
RECALL_KS = (1, 3, 5)

# 섹션 통짜(최대 89k자)를 그대로 임베딩하면 8192토큰 모델(bge-m3 계열)이 MPS에서 버퍼
# 초과로 크래시한다. 본문을 앞에서부터 캡한다 — 섹션 도입부에 핵심 요약이 모여 있어
# 쿼리 주제는 대개 앞부분에서 매칭된다.
MAX_CHUNK_CHARS = 2000


async def fetch_corpus() -> list[ReportChunk]:
    """report_chunks 전체를 id 순으로 로드 — 검색 코퍼스(섹션 단위 = 정답 청크)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(ReportChunk).order_by(ReportChunk.id))
        return list(result.scalars().all())


def load_queries(path: Path) -> list[dict]:
    """라벨 쿼리셋 로드. '_'로 시작하는 메타 키는 제외하고 queries만 반환한다."""
    if not path.exists():
        print(f"쿼리셋이 없습니다: {path}")
        sys.exit(1)
    queries: list[dict] = json.loads(path.read_text(encoding="utf-8"))["queries"]
    return queries


def evaluate(
    query_vecs: np.ndarray, corpus_vecs: np.ndarray, relevant_idx: list[set[int]]
) -> dict:
    """쿼리별 코사인 랭킹으로 recall@k와 MRR을 계산한다."""
    sims = cosine_similarity(query_vecs, corpus_vecs)  # (n_query, n_corpus)
    recalls: dict[int, list[float]] = {k: [] for k in RECALL_KS}
    rr: list[float] = []
    for row, relevant in zip(sims, relevant_idx):
        ranking = np.argsort(row)[::-1]  # 유사도 내림차순 청크 인덱스
        for k in RECALL_KS:
            top_k = set(ranking[:k].tolist())
            recalls[k].append(len(top_k & relevant) / len(relevant))
        # MRR — 첫 정답이 등장하는 순위(1-based)의 역수
        first = next((i + 1 for i, idx in enumerate(ranking) if idx in relevant), None)
        rr.append(1.0 / first if first else 0.0)
    return {
        **{f"recall@{k}": float(np.mean(recalls[k])) for k in RECALL_KS},
        "mrr": float(np.mean(rr)),
    }


def benchmark_model(
    model_name: str, corpus_texts: list[str], queries: list[dict], relevant_idx: list[set[int]]
) -> dict | None:
    """모델 하나로 코퍼스·쿼리를 임베딩해 지표를 낸다. 로딩 실패는 None(표에서 SKIP)."""
    try:
        client = EmbeddingClient(model_name=model_name)
        corpus_vecs = client.embed_matrix(corpus_texts, task_type="RETRIEVAL_DOCUMENT")
        query_vecs = client.embed_matrix(
            [q["query"] for q in queries], task_type="RETRIEVAL_QUERY"
        )
    except Exception as e:  # noqa: BLE001 — 모델별 격리, 하나 실패해도 나머지 진행
        print(f"  SKIP {model_name} — {type(e).__name__}: {str(e)[:160]}")
        return None
    metrics = evaluate(query_vecs, corpus_vecs, relevant_idx)
    return {"model": model_name, "dim": int(corpus_vecs.shape[1]), **metrics}


def print_corpus_stats(corpus: list[ReportChunk]) -> None:
    lengths = np.array([len(c.content) for c in corpus])
    print(
        f"코퍼스: {len(corpus)}청크 · 원본 길이(자) "
        f"중앙값 {int(np.median(lengths))} / 90퍼센타일 {int(np.percentile(lengths, 90))} "
        f"/ 최대 {int(lengths.max())}"
    )
    print(
        f"  → 임베딩 입력은 앞 {MAX_CHUNK_CHARS}자로 캡(서브청크). "
        "512토큰 모델(ko-sroberta·kf-deberta)은 그보다 더 잘림 — 함께 해석\n"
    )


def print_results(results: list[dict]) -> None:
    header = f"{'model':<32}{'dim':>5}{'recall@1':>10}{'recall@3':>10}{'recall@5':>10}{'mrr':>8}"
    print("\n=== RAG recall 비교 (recall@5 내림차순) ===")
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda x: x["recall@5"], reverse=True):
        print(
            f"{r['model']:<32}{r['dim']:>5}{r['recall@1']:>10.3f}{r['recall@3']:>10.3f}"
            f"{r['recall@5']:>10.3f}{r['mrr']:>8.3f}"
        )


def main() -> None:
    corpus = asyncio.run(fetch_corpus())
    if not corpus:
        print("report_chunks가 비어 있습니다 — 먼저 quarterly 수집으로 청크를 적재하세요.")
        sys.exit(1)
    queries = load_queries(QUERIES_PATH)

    # 라벨의 DB id → 코퍼스 인덱스 매핑. 존재하지 않는 id는 라벨 오류이므로 즉시 멈춘다.
    id_to_idx = {c.id: i for i, c in enumerate(corpus)}
    relevant_idx: list[set[int]] = []
    for q in queries:
        missing = [cid for cid in q["relevant_chunk_ids"] if cid not in id_to_idx]
        if missing:
            print(f"라벨 오류 — 코퍼스에 없는 청크 id {missing} (쿼리: {q['query']!r})")
            sys.exit(1)
        relevant_idx.append({id_to_idx[cid] for cid in q["relevant_chunk_ids"]})

    print(f"쿼리 {len(queries)}건 · 모델 {len(CANDIDATE_MODELS)}종\n")
    print_corpus_stats(corpus)
    corpus_texts = [c.content[:MAX_CHUNK_CHARS] for c in corpus]

    results = []
    for i, model_name in enumerate(CANDIDATE_MODELS, 1):
        print(f"[{i}/{len(CANDIDATE_MODELS)}] {model_name}")
        r = benchmark_model(model_name, corpus_texts, queries, relevant_idx)
        if r:
            results.append(r)
    print_results(results)


if __name__ == "__main__":
    main()
