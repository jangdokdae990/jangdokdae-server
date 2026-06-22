"""분류 체계 적합성 검증 — 적재된 이슈를 기존 7개 frame으로 충분히 분류 가능한가? (일회성 eval)

저장된 confidence가 과신이라(거의 전건 0.9) 미스핏 판별에 못 쓴다. 그래서 각 이슈를 원문(대표기사
제목+본문+서브 헤드라인)으로 다시 구성해, stored frame을 가린 채(blind) 독립 LLM이 7개 frame
정의로 재판정한다. best_frame·fit_score(1~5)·fits_within_seven·suggested_category를 모아
"7개로 충분한가 / 새 분류가 필요한가"를 근거와 함께 집계·출력한다(DB 미변경, 판정만).

사용:
    GOOGLE_CLOUD_PROJECT=<vertex-project> GOOGLE_APPLICATION_CREDENTIALS= \
      uv run python -m scripts.verify_frame_coverage
"""

import argparse
import asyncio
import json
import logging
from collections import Counter
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_vertexai import ChatVertexAI
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.queries import get_cluster_by_id
from services.pipeline.news_analyzer import NewsAnalyzer

logger = logging.getLogger(__name__)

Frame = Literal["EARNINGS", "INCIDENT", "PLAN", "POLICY", "TREND", "OPINION", "PRICE"]

# 7개 frame 정의(분류 프롬프트와 동일 취지를 judge용으로 압축).
FRAME_DEFS = """\
- EARNINGS (실적이 나왔어요): 매출·이익·지표 등 확정된 숫자 발표가 원인 사건.
- INCIDENT (악재가 생겼어요): 사고·소송·수사·리콜·제재·악재성 공시, 유상증자·CB 등 지분 희석.
- PLAN (새 계획을 발표했어요): 신제품·투자·수주·계약·인수·협업·주주환원 등 미래의 약속.
- POLICY (제도가 바뀌어요): 정부·중앙은행·당국의 정책·규제·금리·세금 결정/발표.
- TREND (업황이 달라져요): 수요·공급·가격·점유율 등 업황 변화.
- OPINION (전문가가 평가했어요): 증권사 리포트·목표주가·투자의견 등 전문가 판단.
- PRICE (주가만 움직였어요): 뚜렷한 원인 사건 없이 가격·지수·수급 변동 자체가 중심."""

SYSTEM = f"""너는 주식 초보자용 뉴스 큐레이션 서비스의 '분류 체계 감사자'다.
기준은 "이 뉴스를 독자가 어떻게 받아들여야 하는가"이며, 아래 7개 frame이 그 분류 체계다.

{FRAME_DEFS}

주어진 뉴스에 대해 다음을 판정하라(기존 분류 결과는 모른다고 가정):
- best_frame: 7개 중 가장 잘 맞는 것 1개(반드시 하나는 고른다).
- fit_score: best_frame이 이 뉴스에 얼마나 맞는가. 5=완벽, 3=대체로 맞으나 어색, 1=억지로 끼움.
- fits_within_seven: 7개 체계로 이 뉴스를 적절히 포착할 수 있으면 true. 어디에도 본질이 안 맞으면
  (예: 투자 판단과 무관한 홍보·사회공헌·교육 PR 등) false.
- suggested_category: fits_within_seven=false일 때만 필요한 새 분류명을 짧게. 아니면 빈 문자열.
- reason: 한국어 1~2문장 근거.
JSON만 출력한다."""


class JudgeVerdict(BaseModel):
    best_frame: Frame = Field(description="7개 중 가장 잘 맞는 frame")
    fit_score: int = Field(ge=1, le=5, description="best_frame 적합도 1~5")
    fits_within_seven: bool = Field(description="7개 체계로 적절히 포착 가능한가")
    suggested_category: str = Field(default="", description="미스핏 시 필요한 새 분류명")
    reason: str = Field(description="판정 근거 1~2문장")


def _judge():  # noqa: ANN202
    return ChatVertexAI(
        model=settings.vertex_model,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
        temperature=0.0,
        max_retries=settings.llm_max_retries,
    ).with_structured_output(JudgeVerdict)


def _news_text(issue) -> str:  # noqa: ANN001
    subs = "\n".join(f"- {a.title}" for a in issue.sub_articles) or "(없음)"
    body = (issue.main_article.body or "(본문 미확보 — 제목 기준 판단)")[:4000]
    return f"[제목]\n{issue.main_article.title}\n\n[본문]\n{body}\n\n[서브 헤드라인]\n{subs}"


async def verify(min_size: int = 1) -> None:
    analyzer = NewsAnalyzer()
    judge = _judge()

    # 적재된 분석 행(=판정 대상) 목록.
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(select(NewsAnalysis.cluster_id, NewsAnalysis.frame))
        ).all()
    targets = [(cid, frame) for cid, frame in rows]
    print(f"판정 대상 {len(targets)}건")

    results: list[dict] = []
    for i, (cid, stored_frame) in enumerate(sorted(targets)):
        # 원문 재구성은 건마다 새 세션(연결 오염 격리).
        try:
            async with AsyncSessionLocal() as db:
                cluster = await get_cluster_by_id(db, cid)
                if cluster is None or cluster.size < min_size:
                    continue
                issue = await analyzer._build_issue(db, cluster)  # noqa: SLF001
            verdict: JudgeVerdict = await asyncio.to_thread(
                judge.invoke,
                [SystemMessage(content=SYSTEM), HumanMessage(content=_news_text(issue))],
            )
            agree = verdict.best_frame == stored_frame
            row = {
                "cluster_id": cid,
                "title": issue.main_article.title,
                "stored_frame": stored_frame,
                "best_frame": verdict.best_frame,
                "agree": agree,
                "fit_score": verdict.fit_score,
                "fits_within_seven": verdict.fits_within_seven,
                "suggested_category": verdict.suggested_category,
                "reason": verdict.reason,
            }
            results.append(row)
            mark = "✓" if agree else "✗"
            misfit = "" if verdict.fits_within_seven else f"  ❗새분류={verdict.suggested_category}"
            print(
                f"  [{cid:>3}] stored={stored_frame:9s} judge={verdict.best_frame:9s} {mark} "
                f"fit={verdict.fit_score}{misfit} | {issue.main_article.title[:38]}"
            )
        except Exception as exc:  # noqa: BLE001 — 한 건 실패가 전체를 멈추지 않게
            logger.exception("cluster %s 판정 실패", cid)
            print(f"  [{cid}] 판정 실패: {exc}")
        if settings.llm_request_delay_seconds > 0 and i < len(targets) - 1:
            await asyncio.sleep(settings.llm_request_delay_seconds)

    _summary(results)
    out = "/tmp/frame_coverage_verdicts.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n판정 상세 JSON: {out}")


def _summary(results: list[dict]) -> None:
    n = len(results)
    if not n:
        print("판정 결과 없음")
        return
    agree = sum(r["agree"] for r in results)
    misfit_score = [r for r in results if r["fit_score"] <= 2]
    outside = [r for r in results if not r["fits_within_seven"]]
    print(f"\n=== 요약 (n={n}) ===")
    print(f"  stored=judge 일치: {agree}/{n} ({agree/n*100:.0f}%)")
    print(f"  fit_score 분포: {dict(sorted(Counter(r['fit_score'] for r in results).items()))}")
    print(f"  미스핏(fit<=2): {len(misfit_score)}건")
    print(f"  7개 체계 밖(fits_within_seven=false): {len(outside)}건")
    if outside:
        print("  제안된 새 분류 빈도:")
        for cat, c in Counter(r["suggested_category"] for r in outside).most_common():
            print(f"    - {cat or '(미기재)'}: {c}")
        print("  7개 밖 판정 건:")
        for r in outside:
            print(f"    [{r['cluster_id']}] {r['title'][:40]} → {r['suggested_category']}")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description="7개 frame 분류 체계 적합성 검증")
    parser.add_argument("--min-size", type=int, default=1, help="이 크기 이상 클러스터만")
    args = parser.parse_args()
    asyncio.run(verify(min_size=args.min_size))
