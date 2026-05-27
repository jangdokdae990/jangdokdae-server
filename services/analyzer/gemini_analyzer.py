"""LLM 기반 뉴스 분석기"""
import logging

from app.config import settings
from app.llm.graph import NewsAnalysisGraph
from app.llm.state import NewsAnalysisState

logger = logging.getLogger(__name__)


class GeminiAnalyzer:
    """Vertex AI Gemini를 통한 뉴스 분석 (LangChain/LangGraph)"""

    def __init__(self):
        self.project_id = settings.VERTEX_AI_PROJECT_ID
        self.location = settings.VERTEX_AI_LOCATION
        self.model = settings.VERTEX_AI_MODEL
        self.graph = NewsAnalysisGraph()

    def analyze_news(
        self,
        news_title: str,
        news_content: str,
        news_url: str | None = None,
        source: str | None = None,
    ) -> NewsAnalysisState:
        """뉴스 전체 분석 (필터링 → 엔티티 추출 → 영향도 분석 → 해설 생성)"""
        logger.info(f"뉴스 전체 분석 시작: {news_title[:50]}")
        return self.graph.invoke(
            news_title=news_title,
            news_content=news_content,
            news_url=news_url,
            source=source,
        )

    def generate_explanation(self, news_title: str, news_content: str) -> str:
        """주린이 수준의 뉴스 해설 생성"""
        logger.info(f"LLM 해설 생성: {news_title[:50]}")
        result = self.analyze_news(news_title, news_content)
        return result.get("explanation") or ""

    def extract_entities(self, news_content: str) -> dict:
        """뉴스에서 엔티티 추출 (기업, 산업, 이슈 등)"""
        logger.info("엔티티 추출 시작")
        from app.llm.chains import EntityExtractionChain
        return EntityExtractionChain().invoke(news_content)

    def analyze_impact(
        self,
        news_title: str,
        news_content: str,
        symbol: str | None = None,
    ) -> dict:
        """뉴스의 주식 시장 영향도 분석"""
        logger.info(f"영향도 분석: {symbol or '전체'}")
        from app.llm.chains import ImpactAnalysisChain
        return ImpactAnalysisChain().invoke(
            news_title=news_title,
            news_content=news_content,
            related_companies=symbol or "",
        )

    def filter_news(self, news_title: str, news_summary: str) -> dict:
        """투자자에게 중요한 뉴스인지 판단"""
        logger.info(f"뉴스 필터링: {news_title[:50]}")
        from app.llm.chains import FilterChain
        return FilterChain().invoke(news_title, news_summary)
