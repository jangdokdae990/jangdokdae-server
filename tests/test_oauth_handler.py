# 단독 실행: uv run pytest tests/test_oauth_handler.py -s
"""OAuth 핸들러 단위 테스트 — authorize URL·userinfo 정규화·토큰 교환(외부 호출 mock).

검증 포인트:
- provider별 authorize URL에 state(CSRF)·response_type=code가 실린다.
- provider별 상이한 userinfo 응답을 OAuthUserInfo로 통일 정규화한다.
- authenticate가 token→userinfo 2단계를 거쳐 정규화 결과를 반환한다(MockTransport).
- 토큰 교환 실패(4xx)는 AuthError, 미지원 provider는 ValidationError.
"""

import httpx
import pytest

from app.core.errors import AuthError, ValidationError
from services.auth import oauth_handler
from services.auth.oauth_handler import get_oauth_handler

# provider별 userinfo 원본 응답 — 키 구조가 제각각인 점이 정규화 대상.
_KAKAO_RAW = {
    "id": 111,
    "kakao_account": {"email": "a@k.com", "profile": {"nickname": "카", "profile_image_url": "http://img"}},
}
_GOOGLE_RAW = {"sub": "222", "email": "b@g.com", "name": "구", "picture": "http://pic"}
_NAVER_RAW = {"response": {"id": "333", "email": "c@n.com", "nickname": "네", "profile_image": "http://np"}}


@pytest.fixture
def install_transport(monkeypatch):
    """oauth_handler가 만드는 httpx.AsyncClient에 MockTransport를 끼운다."""

    def install(handler):
        real_client = httpx.AsyncClient

        def factory(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(oauth_handler.httpx, "AsyncClient", factory)

    return install


@pytest.mark.parametrize("provider", ["kakao", "google", "naver"])
def test_authorize_url_carries_state(provider):
    url = get_oauth_handler(provider).build_authorize_url("STATE123")
    assert "state=STATE123" in url
    assert "response_type=code" in url


def test_normalize_kakao():
    info = get_oauth_handler("kakao")._normalize(_KAKAO_RAW)
    assert (info.provider, info.provider_user_id, info.email, info.nickname) == (
        "kakao", "111", "a@k.com", "카",
    )
    assert info.profile_image == "http://img"


def test_normalize_google():
    info = get_oauth_handler("google")._normalize(_GOOGLE_RAW)
    assert (info.provider_user_id, info.email, info.nickname, info.profile_image) == (
        "222", "b@g.com", "구", "http://pic",
    )


def test_normalize_naver():
    info = get_oauth_handler("naver")._normalize(_NAVER_RAW)
    assert (info.provider_user_id, info.email, info.nickname, info.profile_image) == (
        "333", "c@n.com", "네", "http://np",
    )


def test_unsupported_provider_raises():
    with pytest.raises(ValidationError):
        get_oauth_handler("facebook")


async def test_authenticate_exchanges_then_fetches(install_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth/token" in request.url.path:
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, json=_KAKAO_RAW)

    install_transport(handler)
    info = await get_oauth_handler("kakao").authenticate("code123", "STATE123")
    assert info.provider_user_id == "111"
    assert info.email == "a@k.com"


async def test_authenticate_token_failure_raises(install_transport):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "invalid_grant"})

    install_transport(handler)
    with pytest.raises(AuthError):
        await get_oauth_handler("kakao").authenticate("bad", "STATE123")


async def test_authenticate_malformed_userinfo_raises_auth_error(install_transport):
    # provider가 200으로 식별자(id) 없는 본문을 주면 KeyError(500)가 아니라 AuthError(401).
    def handler(request: httpx.Request) -> httpx.Response:
        if "oauth/token" in request.url.path:
            return httpx.Response(200, json={"access_token": "tok"})
        return httpx.Response(200, json={"error": "invalid_token"})  # id 키 없음

    install_transport(handler)
    with pytest.raises(AuthError):
        await get_oauth_handler("kakao").authenticate("code123", "STATE123")
