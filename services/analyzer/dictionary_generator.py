"""Dictionary 후보 생성기 — term 하나를 주린이용 설명으로 바꾼다."""

from typing import Literal, TypedDict

from langchain_google_vertexai import ChatVertexAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.config import settings


class DictionaryDraft(BaseModel):
    term_type: Literal["finance", "domain"] = Field(description="용어 유형")
    definition: str = Field(description="주린이가 이해하기 쉬운 한두 문장 설명")
    example: str | None = Field(description="짧은 예시 문장")


class _State(TypedDict):
    term: str
    draft: DictionaryDraft | None


def _llm(model_name: str):
    return ChatVertexAI(
        model=model_name,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
        temperature=0.2,
        max_retries=settings.llm_max_retries,
    ).with_structured_output(DictionaryDraft)


async def generate_dictionary_draft(term: str) -> DictionaryDraft:
    """LangGraph 단일 노드 생성. 실패 fallback은 호출부가 처리한다."""

    async def generate(state: _State) -> _State:
        prompt = (
            "너는 초보 투자자를 위한 주식/경제 용어 사전 작성자다.\n"
            "어려운 금융 용어를 또 늘어놓지 말고 쉽게 설명한다.\n"
            "투자 조언이나 매수/매도 판단은 하지 않는다.\n"
            "정의와 예시의 모든 문장은 '~입니다/~합니다' 문체로 통일한다.\n"
            f"용어: {state['term']}"
        )
        draft = await _llm(settings.dictionary_model).ainvoke(prompt)
        return {"term": state["term"], "draft": draft}

    graph = StateGraph(_State)
    graph.add_node("generate", generate)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", END)
    result = await graph.compile().ainvoke({"term": term, "draft": None})
    draft = result["draft"]
    if draft is None:
        raise RuntimeError("dictionary draft was not generated")
    return draft
