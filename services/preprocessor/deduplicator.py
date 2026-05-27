"""뉴스 중복 제거기"""
import logging

logger = logging.getLogger(__name__)


class NewsDeduplicator:
    """URL 및 제목 유사도 기반 중복 제거"""

    def remove_by_url(self, news_list: list[dict]) -> list[dict]:
        """URL 기반 중복 제거"""
        logger.info("URL 기반 중복 제거 시작")
        unique_urls: set[str] = set()
        deduped = []

        for news in news_list:
            url = news.get("url", "")
            if url and url not in unique_urls:
                unique_urls.add(url)
                deduped.append(news)

        logger.info(f"{len(news_list)} -> {len(deduped)} (중복 제거)")
        return deduped

    def remove_by_similarity(self, news_list: list[dict], threshold: float = 0.9) -> list[dict]:
        """제목 유사도 기반 중복 제거 (받아쓰기 기사 필터)"""
        logger.info(f"유사도 기반 중복 제거 (threshold={threshold})")
        # TODO: BM25 또는 cosine similarity 기반 구현
        return news_list
