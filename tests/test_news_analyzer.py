"""NewsAnalyzer 통합 테스트 — fetch→classify→generate→persist + 부분 실패 격리 (설계 10 §9).

DB·LLM·본문 fetch를 모두 가짜로 대체한다(외부 호출 없음). graph는 분류·콘텐츠를 바로 반환하는
스텁, db는 commit/rollback 횟수만 세는 가짜, 쿼리 함수는 monkeypatch로 호출을 가로챈다.
"""

import types

import pytest

from app.config import settings
from services.analyzer.schemas import (
    ClassificationResult,
    CompanyTag,
    ContentResult,
    Head,
    HookLines,
)
from services.pipeline import news_analyzer
from services.pipeline.news_analyzer import NewsAnalyzer


class _FakeDB:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


def _content() -> ContentResult:
    return ContentResult(
        title="LLM이 생성한 제목",
        heads=[Head(label="l", question="q", answer="a") for _ in range(4)],
        hook_lines=HookLines(pain="p", neutral="n"),
    )


def _classification(cluster_id: int, relevant: bool = True) -> ClassificationResult:
    # cluster 1은 고신뢰(통과), 그 외는 저신뢰(검수 큐).
    return ClassificationResult(
        scope_reasoning="r",
        scope="회사",
        frame_reasoning="r",
        frame="EARNINGS",
        origin="국내",
        direction="상승",
        confidence=0.9 if cluster_id == 1 else 0.4,
        is_investment_relevant=relevant,
        evidence="e",
        company_tags=[CompanyTag(name="삼성전자", role="primary")],
    )


class _FakeGraph:
    def __init__(self, fail_on=(), review_on=(), irrelevant_on=()):
        self.fail_on = set(fail_on)
        self.review_on = set(review_on)  # generation_review=True 강제(가드 실패 시뮬)
        self.irrelevant_on = set(irrelevant_on)  # 비투자성 → generate 건너뜀(content 없음)

    async def ainvoke(self, state):
        issue = state["issue"]
        assert "db" in state  # 오케스트레이터가 enrich용 db를 넘기는지 확인
        if issue.cluster_id in self.fail_on:
            raise RuntimeError("LLM 호출 실패")
        if issue.cluster_id in self.irrelevant_on:
            # 실제 그래프의 조건부 분기: 비투자성이면 generate 생략 → content 키 없음.
            return {"classification": _classification(issue.cluster_id, relevant=False)}
        return {
            "classification": _classification(issue.cluster_id),
            "content": _content(),
            "generation_review": issue.cluster_id in self.review_on,
        }


async def _fake_fetch(urls):
    list(urls)  # 제너레이터 소비
    return "대표 기사 본문 텍스트"


@pytest.fixture
def patched(monkeypatch):
    saves = {"analysis": [], "docent": [], "marks": []}
    clusters = [
        types.SimpleNamespace(id=1, member_news_ids=[10, 11]),
        types.SimpleNamespace(id=2, member_news_ids=[20]),
    ]

    async def fake_get_unanalyzed(db, run_date, limit):
        return clusters

    async def fake_get_articles(db, ids):
        return [types.SimpleNamespace(title=f"기사{i}", url=f"http://x/{i}") for i in ids]

    async def fake_save_analysis(db, **kw):
        saves["analysis"].append(kw)

    async def fake_save_docent(db, **kw):
        saves["docent"].append(kw)

    async def fake_mark(db, ids):
        saves["marks"].append(ids)

    # 태그→마스터 id 해소는 DB 접근이라 가짜로 대체(기업명 있으면 [99], 섹터는 빈 배열).
    async def fake_resolve_company_ids(db, names):
        return [99] if names else []

    async def fake_resolve_sector_ids(db, names):
        return []

    # 종목 거래소→markets.id 해소도 DB 접근이라 가짜로 대체.
    # 종목 있으면 KOSPI(3), 없고 해외면 GLOBAL(8) 폴백, 국내·종목없음은 빈 값.
    async def fake_resolve_market_ids(db, company_ids, origin):
        if company_ids:
            return [3]
        return [8] if origin == "해외" else []

    monkeypatch.setattr(news_analyzer, "get_unanalyzed_clusters", fake_get_unanalyzed)
    monkeypatch.setattr(news_analyzer, "get_cluster_articles", fake_get_articles)
    monkeypatch.setattr(news_analyzer, "resolve_company_ids", fake_resolve_company_ids)
    monkeypatch.setattr(news_analyzer, "resolve_sector_ids", fake_resolve_sector_ids)
    monkeypatch.setattr(news_analyzer, "resolve_market_ids", fake_resolve_market_ids)
    monkeypatch.setattr(news_analyzer, "save_news_analysis", fake_save_analysis)
    monkeypatch.setattr(news_analyzer, "save_issue_docent", fake_save_docent)
    monkeypatch.setattr(news_analyzer, "mark_news_analyzed", fake_mark)
    monkeypatch.setattr(settings, "llm_request_delay_seconds", 0)
    return saves


async def test_run_analyzes_and_persists(patched):
    analyzer = NewsAnalyzer(graph=_FakeGraph(), body_fetcher=_fake_fetch)
    db = _FakeDB()
    state = await analyzer.run(db)

    assert state["clusters"] == 2
    assert state["analyzed"] == 2
    assert state["needs_review"] == 1  # cluster 2 저신뢰
    assert state["errors"] == []
    assert len(patched["analysis"]) == 2
    assert len(patched["docent"]) == 2
    assert patched["marks"] == [[10, 11], [20]]
    assert db.commits == 2
    # 분류 결과가 그대로 적재됐는지(키워드 인자) 확인.
    assert patched["analysis"][0]["frame"] == "EARNINGS"
    assert patched["analysis"][0]["company_tags"] == [{"name": "삼성전자", "role": "primary"}]
    # 태그를 마스터 id로 해소한 백필이 함께 적재되는지(원문 태그와 별도 컬럼).
    assert patched["analysis"][0]["company_ids"] == [99]
    assert patched["analysis"][0]["sector_ids"] == []
    # issue_docent에도 관심사 매칭 백필(market/sector/company)과 LLM 제목이 적재되는지.
    docent = patched["docent"][0]
    assert docent["title"] == "LLM이 생성한 제목"  # 원문 기사 제목이 아닌 LLM 생성 제목
    assert docent["market_ids"] == [3]  # 종목(삼성전자) 거래소 → KOSPI
    assert docent["sector_ids"] == []
    assert docent["company_ids"] == [99]


async def test_run_isolates_cluster_failures(patched):
    analyzer = NewsAnalyzer(graph=_FakeGraph(fail_on=[2]), body_fetcher=_fake_fetch)
    db = _FakeDB()
    state = await analyzer.run(db)

    assert state["analyzed"] == 1
    assert len(state["errors"]) == 1
    assert "cluster=2" in state["errors"][0]
    assert db.rollbacks == 1
    assert db.commits == 1  # 성공한 cluster 1만 commit


async def test_generation_review_forces_needs_review(patched):
    # cluster 1은 고신뢰(0.9)지만 OPINION 1단 가드 실패(generation_review=True) → 검수 큐.
    analyzer = NewsAnalyzer(graph=_FakeGraph(review_on=[1]), body_fetcher=_fake_fetch)
    db = _FakeDB()
    state = await analyzer.run(db)

    assert state["analyzed"] == 2
    # cluster 1(가드 실패) + cluster 2(저신뢰) 둘 다 needs_review.
    assert state["needs_review"] == 2
    assert patched["analysis"][0]["needs_review"] is True


async def test_run_skips_irrelevant(patched):
    # cluster 2가 비투자성(relevance 필터) → 분류만 적재, issue_docent는 생략.
    analyzer = NewsAnalyzer(graph=_FakeGraph(irrelevant_on=[2]), body_fetcher=_fake_fetch)
    db = _FakeDB()
    state = await analyzer.run(db)

    assert state["analyzed"] == 2
    assert state["skipped_irrelevant"] == 1
    # 분류는 2건 적재되나 콘텐츠는 1건만(비투자성 cluster 2 생략).
    assert len(patched["analysis"]) == 2
    assert len(patched["docent"]) == 1
    # 비투자성 분류 행에 is_investment_relevant=False 반영.
    irrelevant = [a for a in patched["analysis"] if a["is_investment_relevant"] is False]
    assert len(irrelevant) == 1
    # skip돼도 멤버는 분석 완료로 표시(재처리 방지).
    assert patched["marks"] == [[10, 11], [20]]
