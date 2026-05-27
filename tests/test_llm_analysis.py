"""LLM 분석 테스트"""
import pytest

from app.llm.chains import (
    EntityExtractionChain,
    FilterChain,
    ImpactAnalysisChain,
    NewsExplanationChain,
)
from app.llm.graph import NewsAnalysisGraph
from services.analyzer.gemini_analyzer import GeminiAnalyzer


@pytest.fixture
def sample_news():
    """샘플 뉴스"""
    return {
        "title": "삼성전자, AI 칩 개발에 대규모 투자",
        "content": """
        삼성전자가 인공지능 반도체 개발에 향후 5년간 10조원을 투자하기로 결정했습니다.
        이는 글로벌 AI 경쟁에서 뒤처지지 않기 위한 전략적 결정입니다.
        삼성은 고성능 GPU와 NPU 칩 개발에 집중할 계획입니다.
        업계 전문가들은 이번 투자가 반도체 시장의 패러다임 변화를 가져올 것으로 예상합니다.
        """,
        "url": "https://example.com/news/123",
        "source": "연합뉴스"
    }


class TestNewsExplanationChain:
    """뉴스 해설 체인 테스트"""

    def test_chain_initialization(self):
        """체인 초기화 테스트"""
        chain = NewsExplanationChain()
        assert chain is not None
        assert chain.prompt_name == "news_explanation"

    @pytest.mark.skip(reason="Vertex AI 인증 필요")
    def test_generate_explanation(self, sample_news):
        """해설 생성 테스트"""
        chain = NewsExplanationChain()
        result = chain.invoke(
            news_title=sample_news["title"],
            news_content=sample_news["content"]
        )
        assert result is not None
        assert len(result) > 0


class TestEntityExtractionChain:
    """엔티티 추출 체인 테스트"""

    def test_chain_initialization(self):
        """체인 초기화 테스트"""
        chain = EntityExtractionChain()
        assert chain is not None
        assert chain.prompt_name == "entity_extraction"

    @pytest.mark.skip(reason="Vertex AI 인증 필요")
    def test_extract_entities(self, sample_news):
        """엔티티 추출 테스트"""
        chain = EntityExtractionChain()
        result = chain.invoke(news_content=sample_news["content"])

        assert "companies" in result
        assert "industries" in result
        assert "keywords" in result


class TestNewsAnalysisGraph:
    """뉴스 분석 그래프 테스트"""

    def test_graph_initialization(self):
        """그래프 초기화 테스트"""
        graph = NewsAnalysisGraph()
        assert graph is not None
        assert graph.graph is not None

    @pytest.mark.skip(reason="Vertex AI 인증 필요")
    def test_full_analysis(self, sample_news):
        """전체 분석 테스트"""
        graph = NewsAnalysisGraph()
        result = graph.invoke(
            news_title=sample_news["title"],
            news_content=sample_news["content"],
            news_url=sample_news["url"],
            source=sample_news["source"]
        )

        # 결과 검증
        assert result.news_title == sample_news["title"]
        assert result.explanation is not None
        assert result.impact_level in ["high", "medium", "low"]
        assert result.processed_at is not None


class TestGeminiAnalyzer:
    """GeminiAnalyzer 통합 테스트"""

    def test_analyzer_initialization(self):
        """분석기 초기화 테스트"""
        analyzer = GeminiAnalyzer()
        assert analyzer is not None
        assert analyzer.graph is not None

    @pytest.mark.skip(reason="Vertex AI 인증 필요")
    def test_full_news_analysis(self, sample_news):
        """뉴스 전체 분석 테스트"""
        analyzer = GeminiAnalyzer()
        result = analyzer.analyze_news(
            news_title=sample_news["title"],
            news_content=sample_news["content"],
            news_url=sample_news["url"],
            source=sample_news["source"]
        )

        assert result is not None
        assert result.explanation is not None
        assert len(result.errors) == 0
