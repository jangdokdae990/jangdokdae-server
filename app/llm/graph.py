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
        return {"classification": result}

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
        """비투자성(is_investment_relevant=false)이면 생성을 건너뛰고 종료(relevance 필터).

        분류만 남기고 enrich·generate(LLM 호출)를 생략한다. content가 비는 상태로 끝나며,
        NewsAnalyzer가 이를 보고 issue_docent 적재를 건너뛴다(설계 평가 04).
        """
        return "enrich" if state["classification"].is_investment_relevant else "skip"

    graph = StateGraph(AnalysisState)
    graph.add_node("classify", classify_node)
    graph.add_node("enrich", enrich_node)
    graph.add_node("generate", generate_node)
    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route_after_classify, {"enrich": "enrich", "skip": END})
    graph.add_edge("enrich", "generate")
    graph.add_edge("generate", END)
    return graph.compile()
