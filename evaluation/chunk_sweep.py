"""§8.2 청크 크기·overlap 스윕 — 선정 모델 토큰 한계에 맞춘 본문 청킹 탐색.

ko-sroberta는 max_seq_length=128토큰(~250자)이라, 현재 chunk_size=1000자는 임베딩 시 대부분
잘린다(각 청크의 앞부분만 반영 + stride가 커 본문 다수 미커버). 모델 용량에 맞춘 작은 청크가
본문을 촘촘히 덮어 title_body 클러스터링을 개선하는지 본다. α는 설계값 0.3 고정(청크 효과만 분리).

표준 실행(앱 venv): python -m evaluation.chunk_sweep --goldset <골드셋 JSON>
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from evaluation.embeddings import build_input
from evaluation.goldset import load_goldset
from evaluation.metrics import score
from services.embedder.cluster import cluster_news, promote_singletons

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "jhgan/ko-sroberta-multitask"
ALPHA = 0.3
# (chunk_size, overlap) — 모델 ~250자 용량 주변부터 현재값(1000)까지.
CHUNK_CONFIGS = [(128, 32), (200, 50), (256, 64), (384, 96), (512, 128), (1000, 200)]


def run(goldset_path: Path, model: str, out: Path) -> None:
    gs = load_goldset(goldset_path)
    tag = goldset_path.stem
    rows = []
    for chunk_size, overlap in CHUNK_CONFIGS:
        matrix = build_input(
            model, gs.items, "title_body", tag=tag, alpha=ALPHA,
            chunk_size=chunk_size, overlap=overlap,
        )
        labels = promote_singletons(cluster_news(matrix))
        f1 = score(gs.gold_labels, [int(x) for x in labels]).pair_f1
        rows.append((chunk_size, overlap, f1))
        logger.info("  chunk=%d overlap=%d F1=%.3f", chunk_size, overlap, f1)

    best = max(rows, key=lambda r: r[2])
    cur = next(r for r in rows if r[0] == 1000)
    lines = [
        "# §8.2 청크 크기·overlap 스윕 결과",
        "",
        f"> 생성 {datetime.now():%Y-%m-%d %H:%M} · 골드셋 `{goldset_path.name}` · "
        f"임베딩 `{model}` + title_body(α={ALPHA})",
        "",
        "ko-sroberta max_seq_length=128토큰(~250자) — 청크가 그보다 크면 임베딩 시 잘린다.",
        "",
        "| chunk_size(자) | overlap | 쌍별 F1 |",
        "| --- | --- | --- |",
    ]
    for cs, ov, f1 in rows:
        mark = " ◀ best" if (cs, ov, f1) == best else (" (현재)" if cs == 1000 else "")
        lines.append(f"| {cs} | {ov} | {f1:.3f}{mark} |")
    lines += [
        "",
        "## 결론",
        "",
        f"- **최적 청크 {best[0]}자/overlap {best[1]}** (F1 {best[2]:.3f}), "
        f"현재 1000자({cur[2]:.3f}) 대비 ΔF1 {best[2] - cur[2]:+.3f}.",
        f"- 운영 `app/config.py`의 chunk_size/chunk_overlap을 {best[0]}/{best[1]}로 조정 검토(§5).",
        "",
        "## 한계·주의",
        "",
        "- 단일 골드셋·Gemini 자동 라벨 · α=0.3 고정(청크 효과 분리).",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("리포트 저장 %s — 최적 chunk=%d F1=%.3f", out, best[0], best[2])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="§8.2 청크 크기 스윕")
    p.add_argument("--goldset", required=True)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--out", default="docs/evaluation/06-chunk-sweep-result.md")
    args = p.parse_args()
    run(Path(args.goldset), args.model, Path(args.out))


if __name__ == "__main__":
    main()
