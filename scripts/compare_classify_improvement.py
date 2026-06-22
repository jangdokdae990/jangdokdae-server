"""분류 개선 전후 비교(비파괴 A/B) — 기존 적재 분류 vs 개선 프롬프트 재분류 (일회성 eval).

PART 10에서 eval/01·03의 제안(OPINION 우선 규칙·거시 가이드·relevance 필터)을 프롬프트/스키마에
반영했다. 그 효과를 **프로덕션 DB를 건드리지 않고** 확인한다:
- A(Before) = 이미 적재된 `news_analysis`(구 프롬프트 결과). 새 컬럼 의존을 피해 컬럼 단위로 읽는다.
- B(After)  = 개선된 분류기(NewsClassifier)로 원문을 **재분류**한 결과(DB 미저장).
frame 변화·OPINION 회복·거시 교정·relevance 필터 건수를 집계(JSON: /tmp/classify_improvement.json).

사용:
    GOOGLE_CLOUD_PROJECT=<vertex> GOOGLE_APPLICATION_CREDENTIALS= \
      uv run python -m scripts.compare_classify_improvement [--limit N]
"""

import argparse
import asyncio
import json
import logging

from sqlalchemy import select

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.queries import get_cluster_by_id
from services.analyzer.classifier import NewsClassifier
from services.pipeline.news_analyzer import NewsAnalyzer

logger = logging.getLogger(__name__)


def _names(company_tags: list[dict]) -> list[str]:
    return sorted({t.get("name", "") for t in company_tags if t.get("name")})


async def run(limit: int) -> None:
    classifier = NewsClassifier()
    analyzer = NewsAnalyzer()

    # Before 스냅샷 — 새 컬럼(is_investment_relevant) 의존을 피하려 컬럼 단위 select(비파괴).
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    NewsAnalysis.cluster_id,
                    NewsAnalysis.scope,
                    NewsAnalysis.frame,
                    NewsAnalysis.origin,
                    NewsAnalysis.direction,
                    NewsAnalysis.sector_tags,
                    NewsAnalysis.company_tags,
                )
            )
        ).all()
    targets = sorted(rows, key=lambda r: r.cluster_id)
    if limit > 0:
        targets = targets[:limit]
    print(f"비교 대상 {len(targets)}건")

    results: list[dict] = []
    for i, row in enumerate(targets):
        try:
            # 원문 재구성은 건마다 새 세션(연결 오염 격리).
            async with AsyncSessionLocal() as db:
                cluster = await get_cluster_by_id(db, row.cluster_id)
                if cluster is None:
                    continue
                issue = await analyzer._build_issue(db, cluster)  # noqa: SLF001
            after = await asyncio.to_thread(classifier.classify, issue)

            a_comp = _names(row.company_tags)
            b_comp = sorted({t.name for t in after.company_tags})
            rec = {
                "cluster_id": row.cluster_id,
                "title": issue.main_article.title,
                "A": {
                    "frame": row.frame, "scope": row.scope,
                    "sector_tags": list(row.sector_tags), "companies": a_comp,
                },
                "B": {
                    "frame": after.frame, "scope": after.scope,
                    "sector_tags": list(after.sector_tags), "companies": b_comp,
                    "is_investment_relevant": after.is_investment_relevant,
                },
                "diff": {
                    "frame": row.frame != after.frame,
                    "scope": row.scope != after.scope,
                    "sector": set(row.sector_tags) != set(after.sector_tags),
                    "companies": set(a_comp) != set(b_comp),
                },
            }
            results.append(rec)
            flag = "" if after.is_investment_relevant else "  ❗비투자성(filter)"
            mark = "≠" if rec["diff"]["frame"] else "="
            print(
                f"  [{row.cluster_id:>3}] frame {row.frame:9s}{mark}{after.frame:9s}"
                f"{flag} | {issue.main_article.title[:36]}"
            )
        except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 멈추지 않게
            logger.exception("cluster %s 비교 실패", row.cluster_id)
            print(f"  [{row.cluster_id}] 실패: {exc}")
        if settings.llm_request_delay_seconds > 0 and i < len(targets) - 1:
            await asyncio.sleep(settings.llm_request_delay_seconds)

    _summary(results)
    out = "/tmp/classify_improvement.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n상세 비교 JSON: {out}")


def _summary(results: list[dict]) -> None:
    n = len(results)
    if not n:
        print("\n비교 결과 없음")
        return
    frame_chg = [r for r in results if r["diff"]["frame"]]
    opinion_recovered = [
        r for r in results if r["A"]["frame"] != "OPINION" and r["B"]["frame"] == "OPINION"
    ]
    opinion_lost = [
        r for r in results if r["A"]["frame"] == "OPINION" and r["B"]["frame"] != "OPINION"
    ]
    macro_fixed = [
        r for r in results
        if r["A"]["frame"] == "EARNINGS" and r["B"]["frame"] in ("TREND", "POLICY")
    ]
    filtered = [r for r in results if not r["B"]["is_investment_relevant"]]
    print(f"\n=== 요약 (n={n}) ===")
    print(f"  frame 변화: {len(frame_chg)}")
    print(f"  OPINION 회복(비OPINION→OPINION): {len(opinion_recovered)}")
    print(f"  OPINION 이탈(OPINION→비OPINION): {len(opinion_lost)}")
    print(f"  거시 교정(EARNINGS→TREND/POLICY): {len(macro_fixed)}")
    print(f"  relevance 필터(비투자성=false): {len(filtered)}")
    if filtered:
        print("  비투자성으로 걸러진 건:")
        for r in filtered:
            print(f"    [{r['cluster_id']}] {r['title'][:42]}")
    print(f"  scope 변화: {sum(r['diff']['scope'] for r in results)} · "
          f"sector 변화: {sum(r['diff']['sector'] for r in results)} · "
          f"companies 변화: {sum(r['diff']['companies'] for r in results)}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description="분류 개선 전후 비교(비파괴 A/B)")
    parser.add_argument("--limit", type=int, default=0, help="앞에서 N건만(0=전체)")
    args = parser.parse_args()
    asyncio.run(run(limit=args.limit))
