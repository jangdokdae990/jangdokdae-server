"""§8.2 보정 — α(제목/내용 가중치) 스윕 + 중복 임계값(cosine) 데이터 도출.

선정 임베딩(ko-sroberta+title_body) 위에서:
  - α 스윕: title_body 결합 가중치 α를 0~1로 바꿔 클러스터링 F1 최대점 탐색(캐시 재조합).
  - 중복 임계값: 같은-이슈 쌍 vs 다른-이슈 쌍 cosine 분포로 현재 0.95 적절성 확인.
    ※ "같은 이슈" ≠ "동일 기사" — 중복은 같은-이슈 중 최고 cosine 부분집합(분포로 해석).

표준 실행(앱 venv): python -m evaluation.calibrate --goldset <골드셋 JSON>
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from evaluation.embeddings import build_input
from evaluation.goldset import load_goldset
from evaluation.metrics import score
from services.embedder.cluster import cluster_news, promote_singletons

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jhgan/ko-sroberta-multitask"
ALPHAS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
DEDUP_CANDIDATES = [0.80, 0.85, 0.90, 0.92, 0.95, 0.97]


def _alpha_sweep(gs, model: str, tag: str) -> list[tuple[float, float]]:
    out = []
    for alpha in ALPHAS:
        matrix = build_input(model, gs.items, "title_body", tag=tag, alpha=alpha)
        labels = promote_singletons(cluster_news(matrix))
        f1 = score(gs.gold_labels, [int(x) for x in labels]).pair_f1
        out.append((alpha, f1))
        logger.info("  alpha=%.1f F1=%.3f", alpha, f1)
    return out


def _pair_sims(gs, model: str, tag: str) -> tuple[np.ndarray, np.ndarray]:
    """같은-이슈 쌍 / 다른-이슈 쌍의 cosine 배열."""
    matrix = build_input(model, gs.items, "title_body", tag=tag)
    sim = cosine_similarity(matrix)
    gold = np.array(gs.gold_labels)
    n = len(gold)
    iu = np.triu_indices(n, k=1)
    same_mask = gold[iu[0]] == gold[iu[1]]
    sims = sim[iu]
    return sims[same_mask], sims[~same_mask]


def run(goldset_path: Path, model: str, out: Path) -> None:
    gs = load_goldset(goldset_path)
    tag = goldset_path.stem

    logger.info("α 스윕")
    alpha_rows = _alpha_sweep(gs, model, tag)
    best_alpha, best_alpha_f1 = max(alpha_rows, key=lambda r: r[1])

    logger.info("중복 임계값 분포")
    same, diff = _pair_sims(gs, model, tag)

    lines = [
        "# §8.2 보정 — α 가중치 · 중복 임계값",
        "",
        f"> 생성 {datetime.now():%Y-%m-%d %H:%M} · 골드셋 `{goldset_path.name}` · 임베딩 `{model}`",
        "",
        "## α (제목/내용 가중치) 스윕 — title_body, HDBSCAN 기본",
        "",
        "| α(제목) | 쌍별 F1 |",
        "| --- | --- |",
    ]
    for alpha, f1 in alpha_rows:
        mark = " ◀ best" if alpha == best_alpha else ""
        lines.append(f"| {alpha:.1f} | {f1:.3f}{mark} |")
    lines += [
        "",
        f"- **최적 α={best_alpha:.1f}** (F1 {best_alpha_f1:.3f}). 설계 고정값 α=0.3과 비교해 판단.",
        "",
        "## 중복 임계값 — 같은-이슈 vs 다른-이슈 cosine 분포",
        "",
        f"- 같은-이슈 쌍 {len(same)}개: 평균 {same.mean():.3f}, 중앙 {np.median(same):.3f}, "
        f"10번째 백분위 {np.percentile(same, 10):.3f}",
        f"- 다른-이슈 쌍 {len(diff)}개: 평균 {diff.mean():.3f}, "
        f"90번째 {np.percentile(diff, 90):.3f}, 95번째 {np.percentile(diff, 95):.3f}, "
        f"99번째 {np.percentile(diff, 99):.3f}",
        "",
        "| 임계 | 같은-이슈 중 ≥임계 비율 | 다른-이슈 중 ≥임계(오탐) 비율 |",
        "| --- | --- | --- |",
    ]
    for thr in DEDUP_CANDIDATES:
        same_rate = float((same >= thr).mean())
        diff_rate = float((diff >= thr).mean())
        mark = " ◀ 현재" if abs(thr - 0.95) < 1e-9 else ""
        lines.append(f"| {thr:.2f}{mark} | {same_rate * 100:.1f}% | {diff_rate * 100:.2f}% |")
    lines += [
        "",
        "## 결론",
        "",
        f"- α: 데이터 최적은 {best_alpha:.1f}. (설계 고정 0.3)",
        "- 중복 임계값 0.95: 다른-이슈 오탐을 거의 0으로 누르는 보수적 지점인지 위 표로 확인. "
        "같은-이슈 ≠ 동일기사라 0.95는 '거의 동일 기사'만 잡는 의도와 부합.",
        "",
        "## 한계·주의",
        "",
        "- 단일 골드셋·Gemini 자동 라벨. 중복(동일기사) 전용 라벨이 아니라 같은-이슈 프록시.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("리포트 저장 %s — best α=%.1f", out, best_alpha)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="§8.2 α·중복임계 보정")
    p.add_argument("--goldset", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--out", default="docs/evaluation/05-calibration-result.md")
    args = p.parse_args()
    run(Path(args.goldset), args.model, Path(args.out))


if __name__ == "__main__":
    main()
