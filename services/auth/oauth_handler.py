"""OAuth 공통 인터페이스 — provider 핸들러의 베이스와 정규화 타입·팩토리.

각 provider 핸들러는 authorize URL 생성·code→token 교환·userinfo 정규화를 구현한다.
라우터는 provider 문자열로 get_oauth_handler(provider)만 호출하고 분기는 여기서 감춘다.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from app.config import settings
from app.core.errors import AuthError, ValidationError

_HTTP_TIMEOUT = 10.0


@dataclass(frozen=True)
class OAuthUserInfo:
    """provider별 응답을 통일한 사용자 정보 — User upsert 입력."""

    provider: str
    provider_user_id: str
    email: str | None
    nickname: str | None
    profile_image: str | None


class OAuthHandler(ABC):
    """provider 1종에 대한 OAuth 흐름. 구현체는 엔드포인트·정규화만 채운다."""

    provider: str
    authorize_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str
    authorize_scope: str | None = None  # 지정 시 동의 화면 scope로 실린다(예: google).

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def build_authorize_url(self, state: str) -> str:
        """state(CSRF)를 실어 provider 동의 화면 URL을 만든다. provider별 차이는 scope뿐."""
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": state,
        }
        if self.authorize_scope:
            params["scope"] = self.authorize_scope
        return f"{self.authorize_endpoint}?{urlencode(params)}"

    @abstractmethod
    def _normalize(self, raw: dict) -> OAuthUserInfo:
        """provider userinfo 응답 → OAuthUserInfo."""

    async def authenticate(self, code: str, state: str) -> OAuthUserInfo:
        """code→token 교환 후 userinfo를 정규화해 반환."""
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            access_token = await self._exchange_code(client, code, state)
            raw = await self._fetch_userinfo(client, access_token)
        try:
            return self._normalize(raw)
        except (KeyError, TypeError) as exc:
            # provider가 200으로 예상과 다른 본문을 주면(필수 식별자 누락 등) 500 대신 401.
            raise AuthError(f"{self.provider} 사용자 정보 형식이 올바르지 않습니다") from exc

    async def _exchange_code(
        self, client: httpx.AsyncClient, code: str, state: str
    ) -> str:
        data = {
            "grant_type": "authorization_code",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "code": code,
            "state": state,
        }
        response = await client.post(self.token_endpoint, data=data)
        if response.status_code != httpx.codes.OK:
            raise AuthError(f"{self.provider} 토큰 교환 실패")
        access_token = response.json().get("access_token")
        if not access_token:
            raise AuthError(f"{self.provider} 토큰 응답에 access_token이 없습니다")
        return str(access_token)

    async def _fetch_userinfo(
        self, client: httpx.AsyncClient, access_token: str
    ) -> dict:
        response = await client.get(
            self.userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != httpx.codes.OK:
            raise AuthError(f"{self.provider} 사용자 정보 조회 실패")
        return dict(response.json())


def get_oauth_handler(provider: str) -> OAuthHandler:
    """provider 문자열로 핸들러를 만든다. 미지원 provider는 ValidationError(422)."""
    # 순환 import 방지 — 팩토리 호출 시점에 구현체를 import한다.
    from services.auth.google_oauth import GoogleOAuthHandler
    from services.auth.kakao_oauth import KakaoOAuthHandler

    handlers: dict[str, type[OAuthHandler]] = {
        "kakao": KakaoOAuthHandler,
        "google": GoogleOAuthHandler,
    }
    handler_cls = handlers.get(provider)
    if handler_cls is None:
        raise ValidationError(f"지원하지 않는 provider입니다: {provider}")

    credentials = {
        "kakao": (
            settings.oauth_kakao_client_id,
            settings.oauth_kakao_client_secret,
            settings.oauth_kakao_redirect_uri,
        ),
        "google": (
            settings.oauth_google_client_id,
            settings.oauth_google_client_secret,
            settings.oauth_google_redirect_uri,
        ),
    }[provider]
    return handler_cls(*credentials)
