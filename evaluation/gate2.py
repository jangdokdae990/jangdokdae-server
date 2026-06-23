"""Gate 2 — 클러스터링 알고리즘 선정(HDBSCAN vs 그래프), 동일 골드셋 쌍별 F1.

Gate 1에서 고른 임베딩(기본 ko-sroberta + title_body) 위에서 두 알고리즘을 비교한다.
그래프는 단일 임계가 모델 cosine 스케일에 민감하므로 임계 스윕의 **최고 F1**으로 대표한다
(양 알고리즘 모두 파라미터 정밀 튜닝은 §8.2). HDBSCAN은 기본 파라미터.

표준 실행(앱 venv): python -m evaluation.gate2 --goldset scripts/data/goldset_2026-06-16.json
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from evaluation.clusterers import graph_cluster
from evaluation.embeddings import build_input
from evaluation.goldset import load_goldset
from evaluation.metrics import score
from services.embedder.cluster import cluster_news, promote_singletons

logger = logging.getLogger(__name__)

# Gate 1 선정 임베딩 + 교차 확인용 1종.
DEFAULT_MODELS = ["jhgan/ko-sroberta-multitask", "gemini-embedding-001"]
DEFAULT_MODE = "title_body"
DEFAULT_THRESHOLDS = [0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9]


def _hdbscan_f1(matrix, gold: list[int]) -> float:
    labels = promote_singletons(cluster_news(matrix))
    return score(gold, [int(x) for x in labels]).pair_f1


def _graph_best(matrix, gold: list[int], thresholds: list[float]) -> tuple[float, float]:
    """임계 스윕에서 (최고 F1, 그 임계)를 반환한다."""
    best_f1, best_thr = -1.0, thresholds[0]
    for thr in thresholds:
        f1 = score(gold, [int(x) for x in graph_cluster(matrix, threshold=thr)]).pair_f1
        logger.info("    graph thr=%.2f F1=%.3f", thr, f1)
        if f1 > best_f1:
            best_f1, best_thr = f1, thr
    return best_f1, best_thr


def run(
    goldset_path: Path, models: list[str], mode: str, thresholds: list[float], out: Path
) -> None:
    gs = load_goldset(goldset_path)
    tag = goldset_path.stem
    rows = []
    for model in models:
        matrix = build_input(model, gs.items, mode, tag=tag)
        hdb = _hdbscan_f1(matrix, gs.gold_labels)
        logger.info("  %-30s HDBSCAN F1=%.3f", model, hdb)
        graph_f1, graph_thr = _graph_best(matrix, gs.gold_labels, thresholds)
        logger.info("  %-30s graph best F1=%.3f @thr=%.2f", model, graph_f1, graph_thr)
        rows.append((model, hdb, graph_f1, graph_thr))

    lines = [
        "# Gate 2 결과 — 클러스터링 알고리즘 (HDBSCAN vs 그래프)",
        "",
        f"> 생성 {datetime.now():%Y-%m-%d %H:%M} · 골드셋 `{goldset_path.name}` · 입력 `{mode}`",
        "",
        "| 모델 | HDBSCAN F1 | 그래프 best F1 | 그래프 best 임계 | 승자 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for model, hdb, gf1, gthr in rows:
        winner = "HDBSCAN" if hdb >= gf1 else "그래프"
        lines.append(f"| {model} | {hdb:.3f} | {gf1:.3f} | {gthr:.2f} | **{winner}** |")
    lines += [
        "",
        "## 한계·주의",
        "",
        "- 그래프=임계 스윕 best F1(유리하게), HDBSCAN=기본 파라미터. 정밀 튜닝은 §8.2.",
        "- 코퍼스 100% 한국어 · 골드 라벨 Gemini 자동(스팟 검수 전).",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("리포트 저장 %s", out)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Bake-off Gate 2")
    p.add_argument("--goldset", required=True)
    p.add_argument("--models", nargs="*", default=DEFAULT_MODELS)
    p.add_argument("--mode", default=DEFAULT_MODE)
    p.add_argument("--thresholds", nargs="*", type=float, default=DEFAULT_THRESHOLDS)
    p.add_argument("--out", default="docs/evaluation/03-gate2-result.md")
    args = p.parse_args()
    run(Path(args.goldset), args.models, args.mode, args.thresholds, Path(args.out))


if __name__ == "__main__":
    main()
