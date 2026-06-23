"""§8.2 HDBSCAN 파라미터 스윕 — 과병합(precision 낮음) 개선점을 골드셋 쌍별 F1로 찾는다.

Gate 1·2에서 기본 파라미터(mcs=2·ms=1·eom)가 과병합(noise~30% vs 실제 단독 65%, precision~0.49)
을 보였다. 선정 임베딩(ko-sroberta+title_body) 위에서 mcs·min_samples·cluster_selection_method를
그리드 스윕해 F1 최대점을 찾는다. 운영 `cluster_news`는 method를 eom 고정이라, 여기선 HDBSCAN을
직접 호출한다(method 비교 위해). precomputed cosine distance는 운영과 동일.

표준 실행(앱 venv): python -m evaluation.param_sweep --goldset <골드셋 JSON>
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import cast

import hdbscan
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

from evaluation.embeddings import build_input
from evaluation.goldset import load_goldset
from evaluation.metrics import score
from services.embedder.cluster import promote_singletons

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jhgan/ko-sroberta-multitask"
DEFAULT_MODE = "title_body"
MIN_CLUSTER_SIZES = [2, 3, 4, 5]
MIN_SAMPLES = [1, 2, 3, 5]
METHODS = ["eom", "leaf"]


def _cluster(distance: np.ndarray, mcs: int, ms: int, method: str) -> np.ndarray:
    clusterer = hdbscan.HDBSCAN(
        min_cluster_size=mcs, min_samples=ms, metric="precomputed",
        cluster_selection_method=method,
    )
    return cast(np.ndarray, clusterer.fit_predict(distance))


def run(goldset_path: Path, model: str, mode: str, out: Path) -> None:
    gs = load_goldset(goldset_path)
    matrix = build_input(model, gs.items, mode, tag=goldset_path.stem)
    distance = np.clip(1.0 - cosine_similarity(matrix), 0.0, None).astype(np.float64)
    gold = gs.gold_labels

    rows = []
    for method in METHODS:
        for mcs in MIN_CLUSTER_SIZES:
            for ms in MIN_SAMPLES:
                raw = _cluster(distance, mcs, ms, method)
                noise = float((raw == -1).mean())
                sc = score(gold, [int(x) for x in promote_singletons(raw)])
                rows.append((mcs, ms, method, sc.pair_f1, sc.pair_precision, sc.pair_recall, noise))
                logger.info(
                    "  mcs=%d ms=%d %-4s F1=%.3f P=%.3f R=%.3f noise=%.0f%%",
                    mcs, ms, method, sc.pair_f1, sc.pair_precision, sc.pair_recall, 100 * noise,
                )

    ranked = sorted(rows, key=lambda r: r[3], reverse=True)
    baseline = next(r for r in rows if r[:3] == (2, 1, "eom"))

    lines = [
        "# §8.2 HDBSCAN 파라미터 스윕 결과",
        "",
        f"> 생성 {datetime.now():%Y-%m-%d %H:%M} · 골드셋 `{goldset_path.name}` · "
        f"임베딩 `{model}` + `{mode}`",
        "",
        f"기준선(mcs=2·ms=1·eom, 운영 현재값): F1 {baseline[3]:.3f} · "
        f"P {baseline[4]:.3f} · R {baseline[5]:.3f} · noise {baseline[6] * 100:.0f}%",
        "",
        "## 상위 10 (쌍별 F1 내림차순)",
        "",
        "| 순위 | mcs | min_samples | method | F1 | P | R | noise |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rank, (mcs, ms, method, f1, p, r, noise) in enumerate(ranked[:10], 1):
        lines.append(
            f"| {rank} | {mcs} | {ms} | {method} | **{f1:.3f}** | {p:.3f} | {r:.3f} | "
            f"{noise * 100:.0f}% |"
        )

    best = ranked[0]
    lines += [
        "",
        "## 결론",
        "",
        f"- **최적 파라미터**: mcs={best[0]} · min_samples={best[1]} · {best[2]} "
        f"→ F1 {best[3]:.3f} (P {best[4]:.3f}·R {best[5]:.3f}), "
        f"기준선 대비 ΔF1 {best[3] - baseline[3]:+.3f}.",
        "- 운영 `cluster_news`는 method가 eom 고정 — leaf 유리 시 파라미터 노출 필요(§5).",
        "",
        "## 한계·주의",
        "",
        "- 단일 골드셋·Gemini 자동 라벨 — 절대값보다 상대 개선폭으로 해석.",
        "- α(0.3)·중복 임계(0.95)는 본 스윕에서 고정.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("리포트 저장 %s — 최적 mcs=%d ms=%d %s F1=%.3f",
                out, best[0], best[1], best[2], best[3])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="§8.2 HDBSCAN 파라미터 스윕")
    p.add_argument("--goldset", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--mode", default=DEFAULT_MODE)
    p.add_argument("--out", default="docs/evaluation/04-param-sweep-result.md")
    args = p.parse_args()
    run(Path(args.goldset), args.model, args.mode, Path(args.out))


if __name__ == "__main__":
    main()
