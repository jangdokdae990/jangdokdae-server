"""실험 — 요약-우선(summary-first) vs 원문-입력 비교 (일회성).

가설: 대표기사 원문 대신 "필요한 핵심만 요약"한 텍스트를 분류·생성 입력으로 넣으면 결과가 어떻게
달라지는가. Variant A(원문)는 이미 적재된 news_analysis·issue_docent를 기준선으로 재사용하고,
Variant B(요약-우선)는 본문을 요약해 Issue.body에 넣어 classify→generate를 다시 돌려 비교한다.
프로덕션 코드·DB 미변경. 결과는 콘솔 + /tmp/summary_first_compare.json.

사용:
    GOOGLE_CLOUD_PROJECT=<vertex-project> GOOGLE_APPLICATION_CREDENTIALS= \
      uv run python -m scripts.compare_summary_first --limit 5
"""

import argparse
import asyncio
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_vertexai import ChatVertexAI
from sqlalchemy import select

from app.config import settings
from app.db.base import AsyncSessionLocal
from app.db.orm_models.issue_docent import IssueDocent
from app.db.orm_models.news_analysis import NewsAnalysis
from app.db.orm_models.news_cluster import NewsCluster
from app.db.queries import get_cluster_by_id
from services.analyzer.classifier import NewsClassifier
from services.analyzer.content_generator import ContentGenerator
from services.analyzer.enricher import DataEnricher
from services.analyzer.schemas import Article, Issue
from services.pipeline.news_analyzer import NewsAnalyzer

logger = logging.getLogger(__name__)

SUMMARIZER_SYSTEM = """너는 주식 뉴스 분석 파이프라인의 '본문 요약기'다.
기사 본문에서 **이후 분류·콘텐츠 생성에 필요한 핵심만** 추려 요약한다.
반드시 보존: ① 원인 사건(무슨 일이 일어났나) ② 확정 숫자·지표(금액·수치·비율·일자)
③ 등장한 기업·기관명(정확히, 빠뜨리지 말 것) ④ 호재/악재 방향 단서 ⑤ 핵심 인용·근거 문장.
제거: 광고·구독 유도·기자/매체 상투구·반복·본 사건과 무관한 배경.
한국어로 5~8개의 짧은 문장(또는 불릿). 새로운 사실을 지어내지 말 것. 요약문만 출력한다."""


def _summarizer():  # noqa: ANN202
    return ChatVertexAI(
        model=settings.vertex_model,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
        temperature=0.0,
        max_retries=settings.llm_max_retries,
    )


def _heads_text(heads: list[dict]) -> list[str]:
    return [(h.get("answer") or "") for h in heads]


def _tag_names(company_tags: list[dict]) -> list[str]:
    return sorted({t.get("name", "") for t in company_tags if t.get("name")})


async def _compare_one(
    cluster: NewsCluster, summarizer, classifier: NewsClassifier, generator: ContentGenerator
) -> dict | None:
    analyzer = NewsAnalyzer()
    async with AsyncSessionLocal() as db:
        # Variant A = 적재된 기준선.
        analysis = (
            await db.execute(select(NewsAnalysis).where(NewsAnalysis.cluster_id == cluster.id))
        ).scalars().first()
        docent = (
            await db.execute(select(IssueDocent).where(IssueDocent.cluster_id == cluster.id))
        ).scalars().first()
        if analysis is None or docent is None:
            print(f"  [{cluster.id}] 적재 기준선 없음 — 스킵")
            return None

        # 원문 재구성(본문 fetch).
        issue = await analyzer._build_issue(db, cluster)  # noqa: SLF001
        body = issue.main_article.body or ""
        if not body:
            print(f"  [{cluster.id}] 본문 미확보 — 요약 비교 의미 없어 스킵")
            return None

        # 요약 → Variant B 입력.
        summary_msg = await asyncio.to_thread(
            summarizer.invoke,
            [SystemMessage(content=SUMMARIZER_SYSTEM),
             HumanMessage(content=f"[제목] {issue.main_article.title}\n\n[본문]\n{body[:8000]}")],
        )
        raw = summary_msg.content
        summary = raw if isinstance(raw, str) else str(raw)
        main_b = Article(
            title=issue.main_article.title, body=summary, url=issue.main_article.url
        )
        issue_b = Issue(
            cluster_id=cluster.id, main_article=main_b, sub_articles=issue.sub_articles
        )

        # Variant B 재분류·재생성 (보강은 A/B 공정 위해 동일 로직 적용).
        class_b = await asyncio.to_thread(classifier.classify, issue_b)
        enrich_b = await DataEnricher().enrich(db, class_b, issue_b)
        content_b, _review_b = await asyncio.to_thread(
            generator.generate_with_guard, issue_b, class_b, enrich_b
        )

    a_companies, b_companies = _tag_names(analysis.company_tags), _tag_names(
        [t.model_dump() for t in class_b.company_tags]
    )
    a_heads = _heads_text(docent.content_heads)
    b_heads = [h.answer for h in content_b.heads]
    result = {
        "cluster_id": cluster.id,
        "size": cluster.size,
        "title": issue.main_article.title,
        "body_chars": len(body),
        "summary_chars": len(summary),
        "summary": summary,
        "A": {
            "scope": analysis.scope, "frame": analysis.frame, "origin": analysis.origin,
            "direction": analysis.direction, "sector_tags": list(analysis.sector_tags),
            "companies": a_companies, "term_tags": list(analysis.term_tags), "heads": a_heads,
        },
        "B": {
            "scope": class_b.scope, "frame": class_b.frame, "origin": class_b.origin,
            "direction": class_b.direction, "sector_tags": list(class_b.sector_tags),
            "companies": b_companies, "term_tags": list(class_b.term_tags), "heads": b_heads,
        },
    }
    result["diff"] = {
        "scope": analysis.scope != class_b.scope,
        "frame": analysis.frame != class_b.frame,
        "direction": analysis.direction != class_b.direction,
        "sector": set(analysis.sector_tags) != set(class_b.sector_tags),
        "companies": set(a_companies) != set(b_companies),
    }
    _print_one(result)
    return result


def _print_one(r: dict) -> None:
    d, a, b = r["diff"], r["A"], r["B"]
    comp = round(r["summary_chars"] / r["body_chars"] * 100) if r["body_chars"] else 0
    print(f"\n=== [{r['cluster_id']}] {r['title'][:46]} (size={r['size']}) ===")
    print(f"  본문 {r['body_chars']}자 → 요약 {r['summary_chars']}자 (압축 {comp}%)")
    mk = lambda x: "≠" if x else "="  # noqa: E731
    print(f"  scope {mk(d['scope'])}: A={a['scope']} B={b['scope']}")
    print(f"  frame {mk(d['frame'])}: A={a['frame']} B={b['frame']}")
    print(f"  direction {mk(d['direction'])}: A={a['direction']} B={b['direction']}")
    print(f"  sector {mk(d['sector'])}: A={a['sector_tags']} B={b['sector_tags']}")
    print(f"  companies {mk(d['companies'])}: A={a['companies']} B={b['companies']}")
    print(f"  head1  A: {(a['heads'][0] if a['heads'] else '')[:90]}")
    print(f"  head1  B: {(b['heads'][0] if b['heads'] else '')[:90]}")


async def run(limit: int, cluster_id: int | None) -> None:
    summarizer, classifier, generator = _summarizer(), NewsClassifier(), ContentGenerator()
    # 대상: 적재된(news_analysis 존재) 클러스터를 크기 큰 순으로.
    async with AsyncSessionLocal() as db:
        if cluster_id is not None:
            c = await get_cluster_by_id(db, cluster_id)
            clusters = [c] if c else []
        else:
            analyzed = select(NewsAnalysis.cluster_id)
            stmt = (
                select(NewsCluster).where(NewsCluster.id.in_(analyzed))
                .order_by(NewsCluster.size.desc(), NewsCluster.importance.desc()).limit(limit)
            )
            clusters = list((await db.execute(stmt)).scalars().all())
    if not clusters:
        print("대상 클러스터 없음")
        return

    print(f"비교 대상 {len(clusters)}건: {[c.id for c in clusters]}")
    results: list[dict] = []
    for i, c in enumerate(clusters):
        try:
            r = await _compare_one(c, summarizer, classifier, generator)
            if r:
                results.append(r)
        except Exception as exc:  # noqa: BLE001
            logger.exception("cluster %s 비교 실패", c.id)
            print(f"  [{c.id}] 실패: {exc}")
        if settings.llm_request_delay_seconds > 0 and i < len(clusters) - 1:
            await asyncio.sleep(settings.llm_request_delay_seconds)

    _summary(results)
    out = "/tmp/summary_first_compare.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n상세 비교 JSON: {out}")


def _summary(results: list[dict]) -> None:
    n = len(results)
    if not n:
        print("\n비교 결과 없음")
        return
    chg = lambda k: sum(r["diff"][k] for r in results)  # noqa: E731
    avg_comp = round(sum(r["summary_chars"] / r["body_chars"] for r in results) / n * 100)
    print(f"\n=== 요약 (n={n}) ===")
    print(f"  평균 압축률(요약/본문): {avg_comp}%")
    print(
        f"  분류 변화(건수) — scope {chg('scope')} · frame {chg('frame')} · "
        f"direction {chg('direction')} · sector {chg('sector')} · companies {chg('companies')}"
    )


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )
    parser = argparse.ArgumentParser(description="요약-우선 vs 원문-입력 A/B 비교")
    parser.add_argument("--limit", type=int, default=5, help="크기 큰 순 N건 (기본 5)")
    parser.add_argument("--cluster-id", type=int, default=None, help="특정 클러스터만")
    args = parser.parse_args()
    asyncio.run(run(limit=args.limit, cluster_id=args.cluster_id))
