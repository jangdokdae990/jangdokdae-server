"""LangChain 기반 뉴스 분석 체인"""
import json
import logging
from typing import Any

from langchain_google_vertexai import VertexAI

from app.config import settings
from app.llm.prompt_loader import PromptLoader

logger = logging.getLogger(__name__)


class BaseLLMChain:
    """기본 LLM 체인 클래스"""

    def __init__(self, prompt_name: str):
        self.prompt_loader = PromptLoader()
        self.prompt_name = prompt_name
        self.prompt_data = self.prompt_loader.load(prompt_name)

        # Vertex AI 클라이언트 초기화
        self.llm = VertexAI(
            project=settings.VERTEX_AI_PROJECT_ID,
            location=settings.VERTEX_AI_LOCATION,
            model_name=self.prompt_data.get("model", settings.VERTEX_AI_MODEL),
            temperature=self.prompt_data.get("temperature", 0.7),
            max_output_tokens=self.prompt_data.get("max_tokens", 1000),
        )

    def invoke(self, **kwargs) -> Any:
        """체인 실행"""
        raise NotImplementedError

    def _format_prompt(self, **kwargs) -> str:
        """프롬프트 포매팅"""
        return self.prompt_loader.format_prompt(self.prompt_name, **kwargs)


class NewsExplanationChain(BaseLLMChain):
    """뉴스 해설 생성 체인"""

    def __init__(self):
        super().__init__("news_explanation")

    def invoke(self, news_title: str, news_content: str) -> str:
        """
        뉴스에 대한 주린이 수준의 해설 생성

        Args:
            news_title: 뉴스 제목
            news_content: 뉴스 본문

        Returns:
            해설 텍스트
        """
        logger.info(f"뉴스 해설 생성 시작: {news_title[:50]}")

        prompt = self._format_prompt(
            news_title=news_title,
            news_content=news_content
        )

        try:
            response = self.llm.invoke(prompt)
            logger.info("뉴스 해설 생성 완료")
            return response
        except Exception as e:
            logger.error(f"뉴스 해설 생성 오류: {e}")
            raise


class EntityExtractionChain(BaseLLMChain):
    """엔티티 추출 체인"""

    def __init__(self):
        super().__init__("entity_extraction")

    def invoke(self, news_content: str) -> dict:
        """
        뉴스에서 엔티티 추출

        Args:
            news_content: 뉴스 본문

        Returns:
            엔티티 딕셔너리
            {
                "companies": [...],
                "industries": [...],
                "keywords": [...],
                "impact_keywords": {...}
            }
        """
        logger.info("엔티티 추출 시작")

        prompt = self._format_prompt(news_content=news_content)

        try:
            response = self.llm.invoke(prompt)

            # JSON 파싱 시도
            try:
                # 응답에서 JSON 추출
                json_start = response.find('{')
                json_end = response.rfind('}') + 1

                if json_start != -1 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    entities = json.loads(json_str)
                    logger.info("엔티티 추출 완료")
                    return entities
            except json.JSONDecodeError:
                logger.warning("JSON 파싱 실패, 기본값 반환")

            return {
                "companies": [],
                "industries": [],
                "keywords": [],
                "impact_keywords": {"positive": [], "negative": []}
            }
        except Exception as e:
            logger.error(f"엔티티 추출 오류: {e}")
            raise


class ImpactAnalysisChain(BaseLLMChain):
    """영향도 분석 체인"""

    def __init__(self):
        super().__init__("impact_analysis")

    def invoke(self, news_title: str, news_content: str, related_companies: str = "") -> dict:
        """
        뉴스의 주식 시장 영향도 분석

        Args:
            news_title: 뉴스 제목
            news_content: 뉴스 본문
            related_companies: 관련 회사 정보 (선택사항)

        Returns:
            영향도 분석 결과
            {
                "impact_level": "high|medium|low",
                "reason": "판단 이유",
                "affected_companies": [...],
                "affected_industries": [...],
                "time_horizon": "immediate|short_term|long_term"
            }
        """
        logger.info("영향도 분석 시작")

        prompt = self._format_prompt(
            news_title=news_title,
            news_content=news_content,
            related_companies=related_companies or "정보 없음"
        )

        try:
            response = self.llm.invoke(prompt)

            # JSON 파싱 시도
            try:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1

                if json_start != -1 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    analysis = json.loads(json_str)
                    logger.info("영향도 분석 완료")
                    return analysis
            except json.JSONDecodeError:
                logger.warning("JSON 파싱 실패, 기본값 반환")

            return {
                "impact_level": "medium",
                "reason": "분석 실패",
                "affected_companies": [],
                "affected_industries": [],
                "time_horizon": "short_term"
            }
        except Exception as e:
            logger.error(f"영향도 분석 오류: {e}")
            raise


class FilterChain(BaseLLMChain):
    """뉴스 필터링 체인"""

    def __init__(self):
        super().__init__("filter")

    def invoke(self, news_title: str, news_summary: str) -> dict:
        """
        주식 투자자에게 중요한 뉴스인지 판단

        Args:
            news_title: 뉴스 제목
            news_summary: 뉴스 요약

        Returns:
            필터링 결과
            {
                "is_important": bool,
                "confidence": float (0.0-1.0),
                "reason": str
            }
        """
        logger.info(f"뉴스 필터링: {news_title[:50]}")

        prompt = self._format_prompt(
            news_title=news_title,
            news_summary=news_summary
        )

        try:
            response = self.llm.invoke(prompt)

            # JSON 파싱 시도
            try:
                json_start = response.find('{')
                json_end = response.rfind('}') + 1

                if json_start != -1 and json_end > json_start:
                    json_str = response[json_start:json_end]
                    result = json.loads(json_str)
                    logger.info(f"필터링 결과: {'포함' if result.get('is_important') else '제외'}")
                    return result
            except json.JSONDecodeError:
                logger.warning("JSON 파싱 실패, 기본값 반환")

            return {
                "is_important": True,
                "confidence": 0.5,
                "reason": "분석 실패"
            }
        except Exception as e:
            logger.error(f"필터링 오류: {e}")
            raise
