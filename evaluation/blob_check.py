"""§8.3 거대 블롭(과병합) 재현 점검 — 대형 이벤트일(06-15)에서 클러스터 크기 분포를 본다.

구 설계(제목 단독)에서 06-15에 size=99 거대 블롭(여러 별개 이슈가 한 덩어리)이 났다. 재설계
임베딩(제목+본문 가중평균)·선정 모델(ko-sroberta)에서 블롭이 재현되는지 **클러스터 크기**로 확인한다
(gold 라벨 불필요 — 과병합은 크기 현상). 비교: 모델×입력 조합별 최대 클러스터 크기·상위 크기.

표준 실행(앱 venv): python -m evaluation.blob_check --goldset scripts/data/goldset_2026-06-15.json
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path

import numpy as np

from evaluation.embeddings import build_input
from services.embedder.cluster import cluster_news

logger = logging.getLogger(__name__)

CONFIGS = [
    ("gemini-embedding-001", "title"),       # 구 설계 근사(제목 단독)
    ("gemini-embedding-001", "title_body"),
    ("jhgan/ko-sroberta-multitask", "title"),
    ("jhgan/ko-sroberta-multitask", "title_body"),  # 선정 조합
]


def _sizes(labels: np.ndarray) -> list[int]:
    """noise(-1) 제외 클러스터 크기 내림차순."""
    counts = Counter(int(x) for x in labels if x != -1)
    return sorted(counts.values(), reverse=True)


def run(goldset_path: Path, out: Path) -> None:
    items = json.loads(goldset_path.read_text(encoding="utf-8"))["items"]
    tag = goldset_path.stem
    rows = []
    for model, mode in CONFIGS:
        matrix = build_input(model, items, mode, tag=tag)
        labels = cluster_news(matrix)  # 원시 레이블(-1=noise) — 크기 관찰엔 승격 불필요
        sizes = _sizes(labels)
        top = sizes[:3] if sizes else [0]
        noise = float((labels == -1).mean())
        rows.append((model, mode, len(sizes), max(sizes, default=0), top, noise))
        logger.info(
            "  %-30s %-11s 클러스터=%d 최대=%d 상위3=%s noise=%.0f%%",
            model, mode, len(sizes), max(sizes, default=0), top, 100 * noise,
        )

    lines = [
        "# §8.3 거대 블롭(과병합) 재현 점검 — 06-15 대형 이벤트일",
        "",
        f"> 생성 {datetime.now():%Y-%m-%d %H:%M} · 골드셋 `{goldset_path.name}` ({len(items)}건)",
        "",
        "구 설계(제목 단독)에서 06-15에 size=99 블롭 발생. 재설계 임베딩에서 재현 여부 확인.",
        "",
        "| 모델 | 입력 | 클러스터 수 | 최대 크기 | 상위 3 크기 | noise |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for model, mode, n, mx, top, noise in rows:
        lines.append(
            f"| {model} | {mode} | {n} | **{mx}** | {top} | {noise * 100:.0f}% |"
        )
    # 선정 조합(ko-sroberta+title_body)의 최대 크기로 자동 판정. 구 블롭은 size=99였다.
    blob_threshold = 30
    selected = next(
        r for r in rows if r[0] == "jhgan/ko-sroberta-multitask" and r[1] == "title_body"
    )
    mx = selected[3]
    verdict = (
        f"**블롭 재현됨** (선정 조합 최대 {mx}) — 추가 분리 필요"
        if mx >= blob_threshold
        else f"**블롭 미재현** (선정 조합 최대 {mx} « 구 블롭 99) — 재설계 임베딩이 과병합 완화"
    )
    lines += [
        "",
        "## 해석",
        "",
        f"- {verdict}.",
        "- 최대 클러스터 크기가 수십 이상이면 과병합(여러 이슈가 한 덩어리) 의심. "
        "Gate 1의 낮은 precision(~0.49)은 거대 블롭이 아니라 **분산형 소과병합**임을 시사.",
        "",
        "## 한계·주의",
        "",
        "- gold 라벨 없이 크기만 관찰(과병합은 크기 현상). 정밀 평가는 라벨링 후 F1.",
        "- HDBSCAN 기본 파라미터.",
        "",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    logger.info("리포트 저장 %s", out)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="§8.3 거대 블롭 점검")
    p.add_argument("--goldset", required=True)
    p.add_argument("--out", default="docs/evaluation/08-blob-check-result.md")
    args = p.parse_args()
    run(Path(args.goldset), Path(args.out))


if __name__ == "__main__":
    main()
