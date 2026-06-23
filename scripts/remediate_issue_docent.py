"""기존 issue_docent 행 1회성 리메디에이션 (설계 15).

품질 게이트·term_spans 필터는 앞으로 생성되는 콘텐츠에만 적용되므로, 이미 저장된 행을
규칙 기반(id 하드코딩 없이)으로 정리한다:
  1) issue_docent.term_spans를 content_heads 본문에 실제 등장하는 term만 남기도록 정리
     (생성기 content_generator._filter_term_spans_in_body와 같은 규칙).
  2) honest-blank head 수가 settings.max_blank_heads 이상이면 해당 클러스터의
     news_analysis.needs_review=True로 격리(품질 게이트와 동일한 격리 대상).
term_spans가 바뀌거나 needs_review가 올라가는 행만 UPDATE한다.

기존 컬럼만 다루므로 새 컬럼(market_ids 등) 마이그레이션 적용 여부와 무관하게 동작하도록
명시 컬럼만 SELECT한다(needs_review는 issue_docent가 아니라 news_analysis 컬럼).

사용:
    python -m scripts.remediate_issue_docent            # dry-run (변경 미리보기, 쓰기 없음)
    python -m scripts.remediate_issue_docent --apply    # 실제 UPDATE (프로덕션 쓰기)
"""

import argparse
import asyncio
import json

from sqlalchemy import text

from app.config import settings
from app.db.base import AsyncSessionLocal
from services.analyzer import frames


def _filtered_term_spans(term_spans: list[dict], content_heads: list[dict]) -> list[dict]:
    """content_heads 본문에 term이 실제 등장하는 term_span만 남긴다(생성기와 동일 규칙)."""
    body = " ".join((h or {}).get("answer", "") for h in content_heads)
    return [s for s in term_spans if s.get("term") and s["term"] in body]


async def _run(apply: bool) -> None:
    async with AsyncSessionLocal() as db:
        # needs_review는 news_analysis에 있으므로 cluster_id로 LEFT JOIN해 현재 값을 함께 읽는다.
        rows = (
            await db.execute(
                text(
                    "SELECT d.id, d.cluster_id, d.content_heads, d.term_spans, "
                    "a.needs_review "
                    "FROM issue_docent d "
                    "LEFT JOIN news_analysis a ON a.cluster_id = d.cluster_id "
                    "ORDER BY d.id"
                )
            )
        ).mappings().all()

        term_changes = 0
        review_changes = 0
        for row in rows:
            heads = row["content_heads"] or []
            spans = row["term_spans"] or []
            new_spans = _filtered_term_spans(spans, heads)
            answers = [(h or {}).get("answer", "") for h in heads]
            blank = frames.count_blank_heads(answers)
            want_review = blank >= settings.max_blank_heads

            new_term = new_spans != spans
            new_rev = want_review and row["needs_review"] is not True
            if not (new_term or new_rev):
                continue

            dropped = [s.get("term") for s in spans if s not in new_spans]
            parts = []
            if new_term:
                parts.append(f"term_spans:-{len(dropped)}{dropped}")
            if new_rev:
                parts.append(f"news_analysis.needs_review→True(blank={blank})")
            print(f"docent_id={row['id']} cluster={row['cluster_id']} " + " ".join(parts))

            if apply:
                if new_term:
                    await db.execute(
                        text(
                            "UPDATE issue_docent SET term_spans = CAST(:ts AS jsonb) "
                            "WHERE id = :id"
                        ),
                        {"ts": json.dumps(new_spans, ensure_ascii=False), "id": row["id"]},
                    )
                    term_changes += 1
                if new_rev:
                    await db.execute(
                        text(
                            "UPDATE news_analysis SET needs_review = true "
                            "WHERE cluster_id = :cid"
                        ),
                        {"cid": row["cluster_id"]},
                    )
                    review_changes += 1
            else:
                term_changes += int(new_term)
                review_changes += int(new_rev)

        if apply:
            await db.commit()
        mode = "적용 완료" if apply else "DRY-RUN (쓰기 없음)"
        print(
            f"\n[{mode}] 대상 {len(rows)}행 중 "
            f"term_spans 변경 {term_changes}행 · needs_review 격리 {review_changes}행"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="issue_docent 무가치·term_spans 리메디에이션")
    parser.add_argument(
        "--apply", action="store_true", help="실제 UPDATE 수행(미지정 시 dry-run)"
    )
    args = parser.parse_args()
    asyncio.run(_run(args.apply))


if __name__ == "__main__":
    main()
