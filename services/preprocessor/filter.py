"""뉴스 필터기"""
import logging

logger = logging.getLogger(__name__)


class NewsFilter:
    """날짜 및 LLM 기반 뉴스 필터링"""

    def filter_by_date(self, news_list: list[dict], days: int = 1) -> list[dict]:
        """최근 N일간의 뉴스만 필터링"""
        logger.info(f"최근 {days}일 뉴스 필터링")
        # TODO: 날짜 기반 필터링 구현
        return news_list

    def filter_by_llm(self, news_list: list[dict]) -> list[dict]:
        """LLM을 통한 주식 영향도 판단 후 필터링"""
        logger.info("LLM 필터링 시작")
        # TODO: LLM 영향도 판단 구현
        return news_list
