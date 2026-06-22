"""Gate 1 오케스트레이션 — 후보 모델 × 입력 구성을 한국어 클러스터링 쌍별 F1로 비교한다.

설계: docs/evaluation/01-bakeoff-design.md §4. 각 (모델, 입력)에 대해
임베딩 → HDBSCAN(기본 파라미터) → 쌍별 F1·ARI·NMI를 내고 리포트로 정리한다.

표준 실행(앱 venv): python -m evaluation.run --goldset scripts/data/goldset_2026-06-16.json
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from evaluation.embeddings import build_input
from evaluation.goldset import load_goldset
from evaluation.metrics import ClusterScores, score
from services.embedder.cluster import cluster_news, promote_singletons

logger = logging.getLogger(__name__)

# 후보 모델(설계 §4) — 다국어 한·영 + 한국어 baseline. 교차언어는 데이터 부재로 미적용.
CANDIDATES = [
    "gemini-embedding-001",
    "BAAI/bge-m3",
    "intfloat/multilingual-e5-large",
    "jhgan/ko-sroberta-multitask",
]
MODES = ["title", "title_body"]


def _run_one(model: str, mode: str, gs, tag: str, alpha: float) -> ClusterScores | None:
    """단일 (모델, 입력) 조합을 평가한다. 모델 로딩·임베딩 실패는 격리해 None."""
    try:
        matrix = build_input(model, gs.items, mode, tag=tag, alpha=alpha)
        labels = promote_singletons(cluster_news(matrix))
        sc = score(gs.gold_labels, [int(x) for x in labels])
        logger.info(
            "  %-34s %-11s F1=%.3f P=%.3f R=%.3f ARI=%.3f",
            model, mode, sc.pair_f1, sc.pair_precision, sc.pair_recall, sc.ari,
        )
        return sc
    except Exception as exc:  # noqa: BLE001 — 한 조합 실패가 전체 비교를 막지 않게 격리
        logger.warning("  %-34s %-11s 실패: %r", model, mode, exc)
        return None


def _write_report(
    results: dict[tuple[str, str], ClusterScores], gs, goldset_path: Path, out_path: Path
) -> None:
    ok = {k: v for k, v in results.items() if v is not None}
    ranked = sorted(ok.items(), key=lambda kv: kv[1].pair_f1, reverse=True)

    lines = [
        "# Gate 1 결과 — 모델 × 입력 구성 (한국어 클러스터링 쌍별 F1)",
        "",
        f"> 생성 {datetime.now():%Y-%m-%d %H:%M} · 골드셋 `{goldset_path.name}` "
        f"({len(gs)}건, gold {gs.meta.get('gold_clusters', '?')}클러스터)",
        "",
        "## 순위 (쌍별 F1 내림차순)",
        "",
        "| 순위 | 모델 | 입력 | 쌍별 F1 | P | R | ARI | NMI |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for rank, ((model, mode), sc) in enumerate(ranked, 1):
        lines.append(
            f"| {rank} | {model} | {mode} | **{sc.pair_f1:.3f}** | "
            f"{sc.pair_precision:.3f} | {sc.pair_recall:.3f} | {sc.ari:.3f} | {sc.nmi:.3f} |"
        )

    # 입력 구성 결정 — title vs title_body 평균 F1.
    def _mean_f1(mode: str) -> float:
        vals = [v.pair_f1 for (_, m), v in ok.items() if m == mode]
        return sum(vals) / len(vals) if vals else 0.0

    title_mean, body_mean = _mean_f1("title"), _mean_f1("title_body")
    win_input = "title_body" if body_mean > title_mean else "title"
    lines += [
        "",
        "## 결론",
        "",
        f"- **입력 구성**: title 평균 F1 {title_mean:.3f} vs title_body {body_mean:.3f} "
        f"→ **{win_input}** 채택.",
    ]
    if ranked:
        (bm, bmode), bsc = ranked[0]
        lines.append(f"- **최고 조합**: `{bm}` + `{bmode}` (F1 {bsc.pair_f1:.3f}).")
    lines += [
        "",
        "## 한계·주의",
        "",
        "- 코퍼스 100% 한국어 — 교차언어 평가 미적용(영어 데이터 부재).",
        "- HDBSCAN 기본(라이브러리 디폴트) 파라미터 — 파라미터 스윕은 §8.2.",
        "- e5 계열은 query/passage prefix 미적용(원문 그대로 임베딩) — 동일 조건 비교 목적.",
        "",
    ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("리포트 저장 %s", out_path)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Bake-off Gate 1")
    p.add_argument("--goldset", required=True, help="라벨링된 골드셋 JSON")
    p.add_argument("--models", nargs="*", default=CANDIDATES, help="후보 모델명")
    p.add_argument("--modes", nargs="*", default=MODES, help="입력 구성")
    p.add_argument("--alpha", type=float, default=0.3, help="제목 가중치(title_body)")
    p.add_argument("--out", default="docs/evaluation/02-gate1-result.md", help="리포트 경로")
    args = p.parse_args()

    goldset_path = Path(args.goldset)
    gs = load_goldset(goldset_path)
    tag = goldset_path.stem
    logger.info(
        "Gate 1 시작 — 골드셋 %d건, 모델 %d, 입력 %d",
        len(gs), len(args.models), len(args.modes),
    )

    results: dict[tuple[str, str], ClusterScores] = {}
    for model in args.models:
        for mode in args.modes:
            sc = _run_one(model, mode, gs, tag, args.alpha)
            if sc is not None:
                results[(model, mode)] = sc

    _write_report(results, gs, goldset_path, Path(args.out))


if __name__ == "__main__":
    main()
