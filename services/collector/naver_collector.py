"""네이버 뉴스 검색 API 수집기"""
import logging

logger = logging.getLogger(__name__)

MARKET_KEYWORDS = [
    "코스피", "코스닥", "금리", "환율",
    "기준금리", "무역수지", "외국인 매수", "증시",
]


class NaverNewsCollector:
    """네이버 뉴스 검색 API를 통한 뉴스 수집"""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def search_market_news(self) -> list[dict]:
        """시장 전체 고정 키워드로 뉴스 검색"""
        logger.info(f"네이버 뉴스 검색: {MARKET_KEYWORDS}")
        # TODO: 네이버 검색 API 호출 구현
        return []

    def search_by_symbol(self, symbol: str) -> list[dict]:
        """종목명으로 뉴스 검색"""
        logger.info(f"종목별 뉴스 검색: {symbol}")
        # TODO: 네이버 검색 API 호출 구현
        return []
