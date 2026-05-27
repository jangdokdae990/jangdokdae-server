"""뉴스 분석 및 해설 생성 비동기 작업"""
import logging

logger = logging.getLogger(__name__)


async def generate_news_explanations():
    """수집된 뉴스에 대한 LLM 해설 생성"""
    logger.info("뉴스 해설 생성 작업 시작")

    # 1. 아직 해설이 없는 뉴스 조회
    # 2. 각 뉴스별로 LLM 해설 생성
    # 3. 해설 저장
    # 4. 엔티티 추출

    pass


async def update_news_embeddings():
    """뉴스의 임베딩 생성 및 업데이트"""
    logger.info("뉴스 임베딩 생성 작업 시작")

    # 1. 아직 임베딩이 없는 뉴스 조회
    # 2. 각 뉴스의 임베딩 생성
    # 3. pgvector에 저장

    pass
