"""LangGraph 상태 정의"""
from typing import TypedDict


class NewsAnalysisState(TypedDict, total=False):
    """뉴스 분석 그래프의 상태"""

    # 입력
    news_title: str
    news_content: str
    news_url: str | None
    source: str | None

    # 필터링
    is_important: bool | None
    filter_confidence: float
    filter_reason: str | None

    # 엔티티 추출
    companies: list[dict]
    industries: list[str]
    keywords: list[str]
    impact_keywords: dict

    # 영향도 분석
    impact_level: str | None      # high, medium, low
    affected_companies: list[dict]
    affected_industries: list[str]
    time_horizon: str | None      # immediate, short_term, long_term

    # 뉴스 해설
    explanation: str | None
    summary: str | None

    # 메타데이터
    processed_at: str | None
    errors: list[str]
