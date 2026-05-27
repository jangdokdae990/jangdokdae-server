"""RSS 피드 뉴스 수집기"""
import logging

logger = logging.getLogger(__name__)

RSS_SOURCES = {
    "yonhapnews": "https://www.yna.co.kr/rss/news/stock.rss",
    "hankyung": "https://feeds.hankyung.com/feed",
}


class RSSCollector:
    """국내외 RSS 피드에서 뉴스 수집"""

    def __init__(self):
        self.sources = RSS_SOURCES

    def collect(self) -> list[dict]:
        logger.info("RSS 피드에서 뉴스 수집 시작")
        # TODO: feedparser로 RSS 파싱 구현
        return []
