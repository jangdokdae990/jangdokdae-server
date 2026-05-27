"""뉴스 수집 비동기 작업"""
import logging

logger = logging.getLogger(__name__)


async def collect_market_news():
    """오늘의 주요 시장 뉴스 수집"""
    logger.info("시장 뉴스 수집 작업 시작")

    # 1. RSS 수집
    # 2. 네이버 뉴스 API 검색
    # 3. 중복 제거
    # 4. LLM 필터링
    # 5. DB에 저장

    pass


async def collect_interest_news():
    """종목/섹터별 맞춤 뉴스 수집"""
    logger.info("관심 종목 뉴스 수집 작업 시작")

    # 1. 모든 사용자의 관심 종목 조회
    # 2. 각 종목별로 뉴스 검색
    # 3. 중복 제거
    # 4. LLM 필터링
    # 5. 사용자별로 뉴스 저장

    pass
