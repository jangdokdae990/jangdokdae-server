"""Finnhub API 수집기"""
import logging

logger = logging.getLogger(__name__)


class FinnhubCollector:
    """Finnhub API를 통한 국외 종목 뉴스 수집"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search_by_ticker(self, ticker: str) -> list[dict]:
        """티커 기반 뉴스 검색"""
        logger.info(f"Finnhub 뉴스 검색: {ticker}")
        # TODO: Finnhub API 호출 구현
        return []
