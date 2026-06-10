"""실험1 — 장독대에 적합한 임베딩 모델 12종을 동일 조건으로 비교하고 모델별로 시각화한다.

설계 05 §11의 모델 확정을 위해 후보를 3종에서 12종으로 넓힌 1차(비지도) 비교다.
12종에는 한국어 금융 도메인 특화 2종(nmixx-bge-m3·kf-deberta-multitask)이 포함된다.
각 모델로 실제 뉴스 제목을 임베딩 → 동일 HDBSCAN 클러스터링 → 자동 지표 + t-SNE 시각화를
output/에 남긴다. 라벨이 없어 pair_auc·ARI는 측정하지 않는다(정식 판정은 라벨 벤치마크).

선정 10종 (관리형 1 + 오픈소스 9, 768/1024 혼합, 검색특화·STS·다국어 다양):
    gemini-embedding-001 / KURE-v1 / KoE5 / arctic-embed-ko / bge-m3 / Qwen3-Embedding-0.6B /
    multilingual-e5-large / KR-SBERT / ko-sroberta(baseline) / KoSimCSE-roberta

주의:
    - e5·Qwen 계열은 query/passage 프리픽스로 성능이 오르지만, 본 비교는 모든 모델에 제목
      원문을 동일하게 넣는다 → 프리픽스 민감 모델은 약간 과소평가될 수 있다(공정성<일관성).
    - 보안상 trust_remote_code(원격 코드 실행)는 쓰지 않는다 → 표준 아키텍처 모델만 선정.
      Qwen3는 설치된 transformers가 네이티브 지원하므로 원격 코드 없이 로드된다.
    - 실패한 모델(다운로드·인증·호환)은 SKIP하고 나머지를 계속 진행한다.

사용:
    python -m scripts.embedding_experiment1 [n_titles]   # 기본 400건
    # gemini 포함하려면 .env GOOGLE_APPLICATION_CREDENTIALS 설정 필요
"""

import asyncio
import json
import sys
from pathlib import Path

from scripts.embedding_cluster_visualize import (
    project_2d,
    save_cluster_members_md,
    save_matplotlib_png,
    save_plotly_html,
)
from scripts.embedding_compare_unsupervised import fetch_titles
from services.embedder.cluster import (
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    cluster_news,
    evaluate_clustering,
)
from services.embedder.embedding_client import EmbeddingClient

# 장독대(한국어 금융 뉴스 클러스터링 + 사업보고서 RAG)에 적합한 후보 12종.
MODELS = [
    "gemini-embedding-001",                          # Vertex 관리형, 768 절단 (현 우승)
    "nlpai-lab/KURE-v1",                             # 한국어 검색 SOTA, 1024
    "nlpai-lab/KoE5",                                # 한국어 e5, 1024
    "dragonkue/bge-m3-ko",                           # 한국어 bge-m3 파인튜닝, 1024
    "nmixx-fin/nmixx-bge-m3",                        # 한국어 금융 도메인 적응 bge-m3, 1024
    "BAAI/bge-m3",                                   # 다국어 base, 1024
    "Qwen/Qwen3-Embedding-0.6B",                     # 2025 오픈 SOTA, 1024
    "intfloat/multilingual-e5-large",                # 다국어 baseline, 1024
    "snunlp/KR-SBERT-V40K-klueNLI-augSTS",           # 한국어 SBERT, 768
    "jhgan/ko-sroberta-multitask",                   # 현재 기본값 baseline, 768
    "upskyy/kf-deberta-multitask",                   # KF-DeBERTa 금융 특화(스키마 유지), 768
    "BM-K/KoSimCSE-roberta-multitask",               # 한국어 SimCSE, 768
]

DEFAULT_N_TITLES = 400
OUTPUT_DIR = Path("output")


def run_model(model_name: str, titles: list[str]) -> dict:
    """모델 하나로 임베딩→클러스터링→지표+시각화. 실패는 status=skip으로 기록 후 계속."""
    try:
        # 표준 아키텍처 모델만 선정 → trust_remote_code 불필요(보안). 호환 안 되면 SKIP.
        client = EmbeddingClient(model_name=model_name)
        embeddings = client.embed_matrix(titles, task_type="CLUSTERING")
    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)[:200]}"
        print(f"    SKIP — {reason}")
        return {"model": model_name, "status": "skip", "reason": reason}

    labels = cluster_news(
        embeddings, min_cluster_size=DEFAULT_MIN_CLUSTER_SIZE, min_samples=DEFAULT_MIN_SAMPLES
    )
    m = evaluate_clustering(embeddings, labels)
    dim = int(embeddings.shape[1])
    sil = m["silhouette"]
    sil_str = f"{sil:.3f}" if sil is not None else "n/a"
    noise_str = f"{m['noise_ratio']:.1%}"
    print(f"    dim={dim} clusters={m['n_clusters']} noise={noise_str} silhouette={sil_str}")

    # 모델별 시각화 산출물 → output/
    coords = project_2d(embeddings)
    slug = model_name.replace("/", "_")
    save_plotly_html(coords, labels, titles, OUTPUT_DIR / f"cluster_{slug}.html", model_name)
    save_matplotlib_png(coords, labels, OUTPUT_DIR / f"cluster_{slug}.png", model_name)
    save_cluster_members_md(titles, labels, OUTPUT_DIR / f"cluster_{slug}.md", model_name)

    return {"model": model_name, "status": "ok", "dim": dim, **m}


def print_summary(results: list[dict]) -> None:
    print("\n=== 실험1 요약 (silhouette은 모델 간 약한 비교 — 모델별 시각화 함께 볼 것) ===")
    header = f"{'model':<46}{'dim':>5}{'clusters':>10}{'noise':>8}{'silhouette':>12}"
    print(header)
    print("-" * len(header))
    ok = [r for r in results if r.get("status") == "ok"]
    ok.sort(key=lambda x: (x["silhouette"] is not None, x["silhouette"] or -1), reverse=True)
    for r in ok:
        sil = f"{r['silhouette']:.3f}" if r["silhouette"] is not None else "n/a"
        print(f"{r['model']:<46}{r['dim']:>5}{r['n_clusters']:>10}{r['noise_ratio']:>7.1%}{sil:>12}")
    skipped = [r["model"] for r in results if r.get("status") == "skip"]
    if skipped:
        print(f"\nSKIP({len(skipped)}): {', '.join(skipped)}")


def main(n_titles: int) -> None:
    titles = asyncio.run(fetch_titles(n_titles))
    print(f"제목 {len(titles)}건 · 모델 {len(MODELS)}종 비교\n")
    if len(titles) < 2:
        print("제목이 너무 적어 클러스터링 불가.")
        return

    OUTPUT_DIR.mkdir(exist_ok=True)
    results = []
    for i, model_name in enumerate(MODELS, 1):
        print(f"\n[{i}/{len(MODELS)}] {model_name}")
        results.append(run_model(model_name, titles))

    print_summary(results)
    summary_path = OUTPUT_DIR / "experiment1_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n요약 JSON: {summary_path}")


if __name__ == "__main__":
    arg_n = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_N_TITLES
    main(arg_n)
