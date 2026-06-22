"""분석 에이전트 LangGraph (설계 10 §8, 06 §18.2 MVP).

단일 에이전트 플로우: classify → enrich → generate → END. 이슈 1건을 받아 분류 → (OPINION 현재가)
보강 → 콘텐츠 생성. fetch_clusters·persist는 DB 경계라 NewsAnalyzer가 그래프 밖에서 처리한다.

노드는 async다 — classify/generate의 동기 LLM 호출은 asyncio.to_thread로 오프로드해 이벤트 루프를
막지 않고, enrich는 DB를 await한다. 따라서 호출부는 graph.ainvoke를 쓴다.
품질 미달 시 supervisor-worker 승급(06 §18.3)은 후속.
"""

from __future__ import annotations

import asyncio

from langgraph.graph import END, StateGraph

from app.config import settings
from app.llm.state import AnalysisState
from services.analyzer.classifier import NewsClassifier
from services.analyzer.content_generator import ContentGenerator
from services.analyzer.enricher import DataEnricher


def build_analysis_graph(
    classifier: NewsClassifier | None = None,
    generator: ContentGenerator | None = None,
    enricher: DataEnricher | None = None,
):
    """classify → enrich → generate 그래프를 컴파일한다. 서비스 객체 주입 가능(테스트용)."""
    clf = classifier or NewsClassifier()
    gen = generator or ContentGenerator()
    enr = enricher or DataEnricher()

    async def classify_node(state: AnalysisState) -> dict:
        result = await asyncio.to_thread(clf.classify, state["issue"])
        # 대표 기사 본문이 임계 미만이면 생성은 honest-blank로 수렴 → 사전 차단 표식.
        body = state["issue"].main_article.body or ""
        insufficient = len(body.strip()) < settings.min_source_body_chars
        return {"classification": result, "source_insufficient": insufficient}

    async def enrich_node(state: AnalysisState) -> dict:
        ctx = await enr.enrich(state["db"], state["classification"], state["issue"])
        return {"enrichment": ctx}

    async def generate_node(state: AnalysisState) -> dict:
        content, review = await asyncio.to_thread(
            gen.generate_with_guard,
            state["issue"],
            state["classification"],
            state.get("enrichment"),
        )
        return {"content": content, "generation_review": review}

    def route_after_classify(state: AnalysisState) -> str:
        """생성(enrich·generate)을 건너뛰고 종료할지 결정 — content가 비는 상태로 끝난다.

        ① 비투자성(is_investment_relevant=false): relevance 필터 — issue_docent 미적재(평가 04).
        ② 원문 본문 부족(source_insufficient): 생성해도 honest-blank라 LLM 호출을 아끼고 종료,
           NewsAnalyzer가 needs_review로 격리한다(설계 15). 두 경우 모두 NewsAnalyzer가 사유를 구분.
        """
        if not state["classification"].is_investment_relevant:
            return "skip"
        if state.get("source_insufficient"):
            return "skip"
        return "enrich"

    graph = StateGraph(AnalysisState)
    graph.add_node("classify", classify_node)
    graph.add_node("enrich", enrich_node)
    graph.add_node("generate", generate_node)
    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route_after_classify, {"enrich": "enrich", "skip": END})
    graph.add_edge("enrich", "generate")
    graph.add_edge("generate", END)
    return graph.compile()
