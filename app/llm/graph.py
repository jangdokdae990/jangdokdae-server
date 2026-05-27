"""LangGraph 기반 뉴스 분석 워크플로우"""
import json
import logging
from datetime import datetime

from langgraph.graph import StateGraph

from app.llm.chains import (
    EntityExtractionChain,
    FilterChain,
    ImpactAnalysisChain,
    NewsExplanationChain,
)
from app.llm.state import NewsAnalysisState

logger = logging.getLogger(__name__)


class NewsAnalysisGraph:
    """뉴스 분석 LangGraph 워크플로우"""

    def __init__(self):
        self.filter_chain = FilterChain()
        self.entity_chain = EntityExtractionChain()
        self.impact_chain = ImpactAnalysisChain()
        self.explanation_chain = NewsExplanationChain()

        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """그래프 빌드"""
        workflow = StateGraph(NewsAnalysisState)

        workflow.add_node("filter", self._filter_node)
        workflow.add_node("extract_entities", self._extract_entities_node)
        workflow.add_node("analyze_impact", self._analyze_impact_node)
        workflow.add_node("generate_explanation", self._generate_explanation_node)

        workflow.set_entry_point("filter")
        workflow.add_edge("filter", "extract_entities")
        workflow.add_edge("extract_entities", "analyze_impact")
        workflow.add_edge("analyze_impact", "generate_explanation")
        workflow.set_finish_point("generate_explanation")

        return workflow.compile()

    def _filter_node(self, state: NewsAnalysisState) -> dict:
        """필터링 노드: 중요한 뉴스인지 판단"""
        logger.info(f"[필터] {state['news_title'][:50]}")

        try:
            summary = state.get("summary") or state["news_content"][:200]

            result = self.filter_chain.invoke(
                news_title=state["news_title"],
                news_summary=summary,
            )

            logger.info(f"[필터] 결과: {'중요' if result.get('is_important') else '미포함'}")
            return {
                "is_important": result.get("is_important", True),
                "filter_confidence": result.get("confidence", 0.5),
                "filter_reason": result.get("reason", ""),
            }
        except Exception as e:
            logger.error(f"[필터] 오류: {e}")
            return {
                "is_important": True,
                "errors": state.get("errors", []) + [f"Filter error: {str(e)}"],
            }

    def _extract_entities_node(self, state: NewsAnalysisState) -> dict:
        """엔티티 추출 노드"""
        logger.info("[엔티티 추출] 시작")

        try:
            result = self.entity_chain.invoke(news_content=state["news_content"])

            logger.info(f"[엔티티 추출] 완료 - 기업: {len(result.get('companies', []))}")
            return {
                "companies": result.get("companies", []),
                "industries": result.get("industries", []),
                "keywords": result.get("keywords", []),
                "impact_keywords": result.get("impact_keywords", {}),
            }
        except Exception as e:
            logger.error(f"[엔티티 추출] 오류: {e}")
            return {"errors": state.get("errors", []) + [f"Entity extraction error: {str(e)}"]}

    def _analyze_impact_node(self, state: NewsAnalysisState) -> dict:
        """영향도 분석 노드"""
        logger.info("[영향도 분석] 시작")

        try:
            companies_str = json.dumps(state.get("companies", []), ensure_ascii=False)

            result = self.impact_chain.invoke(
                news_title=state["news_title"],
                news_content=state["news_content"],
                related_companies=companies_str,
            )

            logger.info(f"[영향도 분석] 완료 - 레벨: {result.get('impact_level')}")
            return {
                "impact_level": result.get("impact_level", "medium"),
                "affected_companies": result.get("affected_companies", []),
                "affected_industries": result.get("affected_industries", []),
                "time_horizon": result.get("time_horizon", "short_term"),
            }
        except Exception as e:
            logger.error(f"[영향도 분석] 오류: {e}")
            return {
                "impact_level": "medium",
                "errors": state.get("errors", []) + [f"Impact analysis error: {str(e)}"],
            }

    def _generate_explanation_node(self, state: NewsAnalysisState) -> dict:
        """해설 생성 노드"""
        logger.info("[해설 생성] 시작")

        try:
            explanation = self.explanation_chain.invoke(
                news_title=state["news_title"],
                news_content=state["news_content"],
            )

            logger.info("[해설 생성] 완료")
            return {
                "explanation": explanation,
                "processed_at": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            logger.error(f"[해설 생성] 오류: {e}")
            return {
                "explanation": f"뉴스 해설 생성에 실패했습니다: {str(e)}",
                "errors": state.get("errors", []) + [f"Explanation generation error: {str(e)}"],
            }

    def invoke(self, news_title: str, news_content: str, **kwargs) -> NewsAnalysisState:
        """그래프 실행"""
        logger.info(f"뉴스 분석 시작: {news_title[:50]}")

        initial_state: NewsAnalysisState = {
            "news_title": news_title,
            "news_content": news_content,
            "news_url": kwargs.get("news_url"),
            "source": kwargs.get("source"),
            "errors": [],
            "companies": [],
            "industries": [],
            "keywords": [],
            "impact_keywords": {},
            "affected_companies": [],
            "affected_industries": [],
            "filter_confidence": 0.0,
        }

        try:
            result = self.graph.invoke(initial_state)
            logger.info(f"뉴스 분석 완료: {news_title[:50]}")
            return result
        except Exception as e:
            logger.error(f"뉴스 분석 실패: {e}")
            initial_state["errors"].append(f"Graph execution error: {str(e)}")
            return initial_state
