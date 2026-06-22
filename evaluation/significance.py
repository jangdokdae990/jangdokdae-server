"""Gate 1 유의성 검정 — 서브샘플 부트스트랩으로 쌍별 F1의 신뢰구간·1위 확률을 낸다.

단일 골드셋 점수 하나로는 모델 간 ΔF1이 노이즈인지 알 수 없다. 골드셋을 반복 서브샘플링
(복원추출은 동일 항목 중복쌍이 TP를 부풀려 제외)해 각 조합의 F1 분포와
"라운드별 최고" 빈도를 추정한다.

표준 실행(앱 venv): python -m evaluation.significance --goldset scripts/data/goldset_2026-06-16.json
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np

from evaluation.embeddings import build_input
from evaluation.goldset import load_goldset
from evaluation.metrics import pairwise_prf
from evaluation.run import CANDIDATES, MODES
from services.embedder.cluster import cluster_news, promote_singletons

logger = logging.getLogger(__name__)

SUBSAMPLE_FRAC = 0.8
DEFAULT_ROUNDS = 300
SEED = 20260621


def _predicted_labels(model: str, mode: str, gs, tag: str) -> np.ndarray:
    matrix = build_input(model, gs.items, mode, tag=tag)
    return promote_singletons(cluster_news(matrix))


def bootstrap(goldset_path: Path, rounds: int) -> None:
    gs = load_goldset(goldset_path)
    tag = goldset_path.stem
    gold = np.array(gs.gold_labels)
    n = len(gs)
    size = int(n * SUBSAMPLE_FRAC)
    rng = np.random.default_rng(SEED)

    # 조합별 예측 레이블(결정적, 캐시 임베딩) 1회 계산.
    configs: list[tuple[str, str]] = [(m, mode) for m in CANDIDATES for mode in MODES]
    preds = {cfg: _predicted_labels(cfg[0], cfg[1], gs, tag) for cfg in configs}

    # 라운드마다 같은 서브샘플 인덱스를 모든 조합에 적용(공정 비교).
    f1s: dict[tuple[str, str], list[float]] = {cfg: [] for cfg in configs}
    wins: dict[tuple[str, str], int] = {cfg: 0 for cfg in configs}
    for _ in range(rounds):
        idx = rng.choice(n, size=size, replace=False)
        g = gold[idx]
        round_f1 = {}
        for cfg, pred in preds.items():
            _, _, f1 = pairwise_prf(list(g), list(pred[idx]))
            f1s[cfg].append(f1)
            round_f1[cfg] = f1
        wins[max(round_f1, key=round_f1.get)] += 1  # type: ignore[arg-type]

    ranked = sorted(configs, key=lambda c: np.mean(f1s[c]), reverse=True)
    logger.info(
        "부트스트랩 %d라운드 (서브샘플 %d/%d) — F1 평균[95%% CI] · 1위확률", rounds, size, n
    )
    for cfg in ranked:
        arr = np.array(f1s[cfg])
        lo, hi = np.percentile(arr, [2.5, 97.5])
        logger.info(
            "  %-30s %-11s F1=%.3f [%.3f, %.3f]  1위 %5.1f%%",
            cfg[0], cfg[1], arr.mean(), lo, hi, 100 * wins[cfg] / rounds,
        )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    p = argparse.ArgumentParser(description="Gate 1 부트스트랩 유의성 검정")
    p.add_argument("--goldset", required=True)
    p.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    args = p.parse_args()
    bootstrap(Path(args.goldset), args.rounds)


if __name__ == "__main__":
    main()
