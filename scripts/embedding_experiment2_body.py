"""실험2 — title-only vs title+body 임베딩 클러스터링 비교 (시각화 포함).

배경(설계 05 §2.2): 현재 뉴스 임베딩은 **제목 단독**이다. 제목은 키워드 밀도가 높아
클러스터링에 실용적으로 충분하다는 가정인데, 본문을 더하면 클러스터링 품질이 달라지는지를
실제 데이터로 측정한다. 실험1(10여 종 모델, 제목 단독, 비지도)과 동일한 모델·클러스터링·
시각화 하니스를 그대로 쓰고, 입력 텍스트만 두 변형으로 바꿔 끝까지 돌려 나란히 비교한다.

변형:
    title_only : title
    title_body : title + "\n" + body[:BODY_CHAR_CAP]   (본문 fetch 후 인메모리 사용·폐기)

본문 fetch:
    분석 단계 도구 fetch_article_body(trafilatura)를 재사용하되, **리다이렉트 추적
    클라이언트를 주입**한다 — 이 실험 당시 프로덕션 fetcher가 follow_redirects를 켜지 않아
    국내 다수 매체의 http→https 301에서 실패함을 발견했고, 2026-06-11 프로덕션에도
    follow_redirects가 적용됐다(article_fetcher.py). 페이월·WAF(investing.com 403)는
    그대로 실패 → 본문 없는 기사는 공정 비교를 위해 표본에서 제외한다.
    본문·snippet은 저장하지 않는다(저작권, 설계 02 §3) — 인메모리 임베딩 후 폐기.

차이 정량화:
    두 변형의 클러스터 라벨을 adjusted_rand_score로 비교한다(ARI 높음=본문이 군집을 거의
    안 바꿈, 낮음=많이 바꿈). silhouette·noise·클러스터 수와 함께 모델별 표로 정리한다.

산출(output/):
    exp2_dataset.json          — 표본(title/body, fetch 통계). 재실행 시 재사용(--refetch로 갱신)
    exp2_compare_<model>.png   — 모델별 좌(title) · 우(title+body) t-SNE 나란히
    exp2_summary.json / .md    — 모델별 지표·델타·ARI 요약

사용:
    python -m scripts.embedding_experiment2_body [n_articles] [model_substr] [--refetch]
    # 예) python -m scripts.embedding_experiment2_body 200            # 전체 모델
    #     python -m scripts.embedding_experiment2_body 150 gemini     # gemini만(파이프라인 검증용)
    # gemini 포함하려면 .env GOOGLE_APPLICATION_CREDENTIALS(Vertex 인증) 필요.
"""

import asyncio
import gc
import json
import sys
from pathlib import Path

import httpx
import matplotlib.pyplot as plt
import numpy as np
from sklearn.metrics import adjusted_rand_score
from sqlalchemy import text

from app.db.base import AsyncSessionLocal
from scripts.embedding_cluster_visualize import (
    project_2d,
    save_cluster_members_md,
    save_plotly_html,
)
from scripts.embedding_experiment1 import MODELS
from services.analyzer.article_fetcher import fetch_article_body
from services.embedder.cluster import (
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_MIN_SAMPLES,
    cluster_news,
    evaluate_clustering,
)
from services.embedder.embedding_client import EmbeddingClient
from utils.http import USER_AGENT

DEFAULT_N_ARTICLES = 200
BODY_CHAR_CAP = 2000  # 본문 앞 N자만 사용(설계 평가 §6 RAG 입력 캡과 동일 — 토큰 한도·일관성)
FETCH_CONCURRENCY = 8
OUTPUT_DIR = Path("output")
DATASET_PATH = OUTPUT_DIR / "exp2_dataset.json"


async def _fetch_rows(n: int) -> list[tuple[str, str]]:
    """분석 대상(is_filtered=false) 뉴스 (title, url)을 최신순 n건."""
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT title, url FROM news WHERE is_filtered = false "
                    "ORDER BY published_at DESC NULLS LAST LIMIT :n"
                ),
                {"n": n},
            )
        ).all()
    return [(r[0], r[1]) for r in rows]


async def build_dataset(n: int) -> dict:
    """뉴스 n건의 본문을 fetch(리다이렉트 추적)해 본문 성공분만 표본으로 만든다."""
    rows = await _fetch_rows(n)
    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    # 리다이렉트 추적 클라이언트 주입 — 프로덕션 fetcher의 http→https 301 실패를 우회.
    async with httpx.AsyncClient(
        timeout=10.0, headers={"User-Agent": USER_AGENT}, follow_redirects=True
    ) as client:

        async def fetch(title: str, url: str) -> tuple[str, str | None]:
            async with sem:
                return title, await fetch_article_body(url, client=client)

        results = await asyncio.gather(*[fetch(t, u) for t, u in rows])

    kept = [
        {"title": t, "body": b[:BODY_CHAR_CAP]} for t, b in results if b is not None
    ]
    stats = {"requested": len(rows), "fetched": len(kept),
             "fetch_rate": round(len(kept) / max(len(rows), 1), 3)}
    print(f"본문 fetch: {stats['fetched']}/{stats['requested']} ({stats['fetch_rate']:.0%}) 성공")
    return {"stats": stats, "items": kept}


def load_or_build_dataset(n: int, refetch: bool) -> dict:
    if DATASET_PATH.exists() and not refetch:
        data: dict = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        print(f"기존 표본 재사용: {DATASET_PATH} ({len(data['items'])}건) — 갱신하려면 --refetch")
        return data
    data = asyncio.run(build_dataset(n))
    OUTPUT_DIR.mkdir(exist_ok=True)
    DATASET_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _metrics(embeddings: np.ndarray) -> tuple[np.ndarray, dict]:
    labels = cluster_news(
        embeddings, min_cluster_size=DEFAULT_MIN_CLUSTER_SIZE, min_samples=DEFAULT_MIN_SAMPLES
    )
    return labels, evaluate_clustering(embeddings, labels)


def save_side_by_side(
    coords_to: np.ndarray, lab_to: np.ndarray,
    coords_tb: np.ndarray, lab_tb: np.ndarray,
    path: Path, model_name: str,
) -> None:
    """좌(title-only) · 우(title+body) t-SNE 산점도를 한 PNG에 나란히."""
    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    for ax, coords, lab, sub in (
        (axes[0], coords_to, lab_to, "title-only"),
        (axes[1], coords_tb, lab_tb, "title+body"),
    ):
        noise = lab == -1
        ax.scatter(coords[noise, 0], coords[noise, 1], c="lightgray", s=10, label="noise")
        ax.scatter(coords[~noise, 0], coords[~noise, 1], c=lab[~noise], cmap="tab20", s=12)
        n_clusters = len(set(lab.tolist())) - (1 if -1 in lab else 0)
        ax.set_title(f"{sub}  (clusters={n_clusters}, noise={noise.mean():.0%})")
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle(f"title-only vs title+body — {model_name}", fontsize=14)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def run_model(model_name: str, titles: list[str], bodies_text: list[str]) -> dict:
    """모델 하나로 두 변형을 임베딩→클러스터링→지표+나란히 시각화. 실패는 skip."""
    try:
        client = EmbeddingClient(model_name=model_name)
        emb_to = client.embed_matrix(titles, task_type="CLUSTERING")
        emb_tb = client.embed_matrix(bodies_text, task_type="CLUSTERING")
    except Exception as e:
        reason = f"{type(e).__name__}: {str(e)[:200]}"
        print(f"    SKIP — {reason}")
        return {"model": model_name, "status": "skip", "reason": reason}
    finally:
        # 모델을 메모리에서 풀어 다음 모델 로드 시 누적 OOM을 막는다(로컬 HF 모델 다중 비교).
        client = None  # type: ignore[assignment]
        gc.collect()

    lab_to, m_to = _metrics(emb_to)
    lab_tb, m_tb = _metrics(emb_tb)
    ari = float(adjusted_rand_score(lab_to, lab_tb))  # 두 변형 군집 일치도(차이 정량화)

    # t-SNE 투영은 변형별 1회만 계산해 PNG·HTML이 공유한다.
    coords_to, coords_tb = project_2d(emb_to), project_2d(emb_tb)
    slug = model_name.replace("/", "_")
    save_side_by_side(coords_to, lab_to, coords_tb, lab_tb,
                      OUTPUT_DIR / f"exp2_compare_{slug}.png", model_name)
    # 정성 검증용 — 변형별 인터랙티브 HTML(hover=제목) + 클러스터 멤버 MD.
    # hover·멤버에는 title+body 블롭이 아니라 제목을 보여준다(읽기 위함).
    for coords, lab, var in ((coords_to, lab_to, "title"), (coords_tb, lab_tb, "body")):
        save_plotly_html(coords, lab, titles, OUTPUT_DIR / f"exp2_{var}_{slug}.html",
                         f"{model_name} [{var}]")
        save_cluster_members_md(titles, lab, OUTPUT_DIR / f"exp2_{var}_{slug}.md",
                                f"{model_name} [{var}]")

    def fmt(m: dict) -> str:
        s = f"{m['silhouette']:.3f}" if m["silhouette"] is not None else "n/a"
        return f"clusters={m['n_clusters']} noise={m['noise_ratio']:.0%} sil={s}"

    print(f"    title : {fmt(m_to)}")
    print(f"    +body : {fmt(m_tb)}   |  두 군집 ARI={ari:.3f}")
    return {
        "model": model_name, "status": "ok", "dim": int(emb_to.shape[1]),
        "title_only": m_to, "title_body": m_tb, "label_ari": ari,
    }


def print_summary(results: list[dict], n_items: int) -> None:
    print(f"\n=== 실험2 요약 — title-only vs title+body (표본 {n_items}건) ===")
    h = f"{'model':<42}{'sil(title)':>11}{'sil(+body)':>11}{'Δsil':>8}{'노이즈Δ':>9}{'군집ARI':>9}"
    print(h)
    print("-" * len(h))
    for r in [x for x in results if x.get("status") == "ok"]:
        to, tb = r["title_only"], r["title_body"]
        s_to = to["silhouette"] or 0.0
        s_tb = tb["silhouette"] or 0.0
        dnoise = tb["noise_ratio"] - to["noise_ratio"]
        print(f"{r['model']:<42}{s_to:>11.3f}{s_tb:>11.3f}{s_tb - s_to:>+8.3f}"
              f"{dnoise:>+8.0%}{r['label_ari']:>9.3f}")
    skipped = [r["model"] for r in results if r.get("status") == "skip"]
    if skipped:
        print(f"\nSKIP({len(skipped)}): {', '.join(skipped)}")
    print("\n해석: Δsil>0 = 본문이 군집 응집을 높임 / 군집ARI 낮을수록 본문이 군집을 많이 바꿈.")


def save_summary_md(results: list[dict], dataset: dict) -> None:
    st = dataset["stats"]
    lines = [
        "# 실험2 — title-only vs title+body 임베딩 클러스터링",
        "",
        f"- 표본: 본문 fetch 성공 **{st['fetched']}/{st['requested']}건** "
        f"({st['fetch_rate']:.0%}, 리다이렉트 추적). 본문 없는 기사는 공정 비교를 위해 제외.",
        f"- 본문 입력 캡: 앞 {BODY_CHAR_CAP}자. 변형: `title` vs `title + 본문`.",
        "- 두 변형 군집 라벨의 ARI로 '본문이 군집을 얼마나 바꾸는가'를 정량화.",
        "",
        "| 모델 | dim | sil(title) | sil(+body) | Δsil | noise(title→+body) | 군집 ARI |",
        "|------|-----|-----------|-----------|------|--------------------|---------|",
    ]
    for r in [x for x in results if x.get("status") == "ok"]:
        to, tb = r["title_only"], r["title_body"]
        s_to = to["silhouette"] or 0.0
        s_tb = tb["silhouette"] or 0.0
        lines.append(
            f"| {r['model']} | {r['dim']} | {s_to:.3f} | {s_tb:.3f} | {s_tb - s_to:+.3f} "
            f"| {to['noise_ratio']:.0%} → {tb['noise_ratio']:.0%} | {r['label_ari']:.3f} |"
        )
    lines += ["", "모델별 좌(title)·우(title+body) t-SNE: `output/exp2_compare_<model>.png`."]
    (OUTPUT_DIR / "exp2_summary.md").write_text("\n".join(lines), encoding="utf-8")


def main(n: int, model_filter: str | None, refetch: bool) -> None:
    dataset = load_or_build_dataset(n, refetch)
    items = dataset["items"]
    if len(items) < 5:
        print("표본이 너무 적어 클러스터링 불가.")
        return
    titles = [it["title"] for it in items]
    bodies_text = [f"{it['title']}\n{it['body']}" for it in items]

    models = [m for m in MODELS if model_filter in m] if model_filter else MODELS
    print(f"표본 {len(items)}건 · 모델 {len(models)}종\n")
    OUTPUT_DIR.mkdir(exist_ok=True)
    results = []
    for i, model_name in enumerate(models, 1):
        print(f"[{i}/{len(models)}] {model_name}")
        results.append(run_model(model_name, titles, bodies_text))

    print_summary(results, len(items))
    save_summary_md(results, dataset)
    (OUTPUT_DIR / "exp2_summary.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n요약: {OUTPUT_DIR / 'exp2_summary.json'} · {OUTPUT_DIR / 'exp2_summary.md'}")


if __name__ == "__main__":
    pos = [a for a in sys.argv[1:] if a != "--refetch"]
    arg_n = int(pos[0]) if len(pos) > 0 and pos[0].isdigit() else DEFAULT_N_ARTICLES
    arg_filter = next((p for p in pos if not p.isdigit()), None)
    main(arg_n, arg_filter, "--refetch" in sys.argv)
