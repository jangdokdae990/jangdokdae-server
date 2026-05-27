"""구글 OAuth 2.0 처리"""
import logging

logger = logging.getLogger(__name__)


class GoogleOAuthHandler:
    """구글 OAuth 2.0 처리"""

    def __init__(self, client_id: str, client_secret: str):
        self.client_id = client_id
        self.client_secret = client_secret

    def get_auth_url(self, redirect_uri: str) -> str:
        """구글 인증 URL 생성"""
        # TODO: 구글 OAuth URL 생성 구현
        return ""

    def get_access_token(self, code: str, redirect_uri: str) -> dict:
        """인가 코드로 액세스 토큰 발급"""
        logger.info("구글 액세스 토큰 발급")
        # TODO: 구글 토큰 발급 API 호출
        return {}

    def get_user_info(self, access_token: str) -> dict:
        """액세스 토큰으로 사용자 정보 조회"""
        logger.info("구글 사용자 정보 조회")
        # TODO: 구글 사용자 정보 API 호출
        return {}
