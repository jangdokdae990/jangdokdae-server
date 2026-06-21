"""Bake-off 골드셋 라벨링 — Gemini로 "같은 단일 사건" 클러스터를 1차 제안한다.

설계: docs/evaluation/01-bakeoff-design.md §2. LLM은 **텍스트(제목)만** 보고 묶어 평가 대상
임베딩과 독립적인 정답(gold)을 만든다(순환 편향 차단). 산출물:
  - goldset JSON의 gold_cluster를 채워 덮어쓴다(클러스터 id, 단독 기사는 고유 singleton id).
  - 사람 스팟 검수용 마크다운(클러스터별 제목 묶음)을 함께 출력한다.

표준 실행(앱 venv): python -m scripts.label_goldset --goldset scripts/data/goldset_2026-06-16.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from langchain_google_vertexai import ChatVertexAI
from pydantic import BaseModel, Field

from app.config import settings

logger = logging.getLogger(__name__)

PROMPT = """다음은 같은 기간에 수집된 한국 경제·증권 뉴스 제목 목록이다(번호: 제목).
**동일한 단일 사건**을 보도하는 기사들을 같은 그룹으로 묶어라.

규칙:
- 같은 사건 = 같은 회사·같은 발표·같은 이벤트를 다룬 기사(통신사 받아쓰기·전재 포함).
- 단순히 같은 종목/주제를 언급한다고 같은 사건이 아니다 — 구체적 사건이 같아야 한다.
- 2건 이상 같은 사건인 그룹만 출력한다. 단독 기사는 출력하지 마라.
- 각 그룹에 사건을 한 줄로 요약(event)하고 해당 기사 번호(ids)를 나열한다.

제목 목록:
{titles}
"""


class Cluster(BaseModel):
    event: str = Field(description="사건 한 줄 요약")
    ids: list[int] = Field(description="이 사건을 보도한 기사 번호들 (2건 이상)")


class ClusterProposal(BaseModel):
    clusters: list[Cluster]


def _build_titles_block(items: list[dict]) -> str:
    return "\n".join(f"{i}: [{it['news_source']}] {it['title']}" for i, it in enumerate(items))


def _assign_gold(items: list[dict], proposal: ClusterProposal) -> dict[int, int]:
    """제안 그룹을 gold_cluster id로 변환. 미포함 기사는 각자 singleton id."""
    n = len(items)
    gold: dict[int, int] = {}
    next_id = 0
    for cluster in proposal.clusters:
        # 유효 범위·중복 방어 — 이미 배정됐거나 범위 밖 id는 건너뛴다.
        members = [i for i in cluster.ids if 0 <= i < n and i not in gold]
        if len(members) < 2:
            continue
        for i in members:
            gold[i] = next_id
        next_id += 1
    # 나머지는 singleton.
    for i in range(n):
        if i not in gold:
            gold[i] = next_id
            next_id += 1
    return gold


def _write_review_md(items: list[dict], proposal: ClusterProposal, path: Path) -> None:
    """사람 스팟 검수용 — 다건 클러스터를 사건별로 묶어 보여준다."""
    lines = ["# 골드셋 라벨 검수 (Gemini 1차 제안)", ""]
    multi = [c for c in proposal.clusters if len([i for i in c.ids if 0 <= i < len(items)]) >= 2]
    lines.append(f"다건 클러스터 {len(multi)}개 — 병합/분할이 필요하면 알려주세요.\n")
    for c in multi:
        lines.append(f"## {c.event}")
        for i in c.ids:
            if 0 <= i < len(items):
                lines.append(f"- ({i}) [{items[i]['news_source']}] {items[i]['title']}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def label(goldset_path: Path, model: str) -> None:
    data = json.loads(goldset_path.read_text(encoding="utf-8"))
    items = data["items"]
    logger.info("라벨링 대상 %d건 (model=%s)", len(items), model)

    llm = ChatVertexAI(
        model=model,
        project=settings.google_cloud_project,
        location=settings.google_cloud_location,
        temperature=0,
    ).with_structured_output(ClusterProposal)
    proposal: ClusterProposal = llm.invoke(PROMPT.format(titles=_build_titles_block(items)))  # type: ignore[assignment]

    gold = _assign_gold(items, proposal)
    for i, it in enumerate(items):
        it["gold_cluster"] = gold[i]

    n_clusters = len(set(gold.values()))
    n_multi = sum(
        1 for c in proposal.clusters if sum(0 <= i < len(items) for i in c.ids) >= 2
    )
    data["meta"]["gold_clusters"] = n_clusters
    data["meta"]["gold_multi_clusters"] = n_multi
    data["meta"]["labeled_by"] = f"gemini:{model}"
    goldset_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    review_path = goldset_path.with_name(goldset_path.stem + "_review.md")
    _write_review_md(items, proposal, review_path)
    logger.info(
        "라벨 완료 — 총 %d클러스터(다건 %d), 검수본 %s", n_clusters, n_multi, review_path
    )


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    p = argparse.ArgumentParser(description="Bake-off 골드셋 Gemini 라벨링")
    p.add_argument("--goldset", required=True, help="골드셋 JSON 경로")
    # 설정 기본값(gemini-3.5-flash)은 현재 리전에 없어 동작 모델을 명시 기본값으로 둔다.
    p.add_argument("--model", default="gemini-2.5-flash", help="라벨링 LLM 모델명")
    args = p.parse_args()
    label(Path(args.goldset), args.model)


if __name__ == "__main__":
    main()
