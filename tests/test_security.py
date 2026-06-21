# 단독 실행: uv run pytest tests/test_security.py -s
"""security 단위 테스트 — JWT 발급·검증, 쿠키 기반 인증 의존성.

검증 포인트:
- access/refresh 토큰이 user_id를 왕복 보존한다.
- 토큰 유형(access↔refresh) 혼용·위조 토큰은 AuthError로 거부한다.
- get_current_user는 쿠키 없으면 401(AuthError), optional은 None으로 guest 허용.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from jose import jwt

from app.config import settings
from app.core.errors import AuthError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    get_current_user_optional,
)


def _signed_token(sub, token_type: str = "access") -> str:
    # 정상 서명·만료지만 sub만 비정상으로 심은 토큰 — int 변환 실패 경로 검증용.
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "type": token_type, "iat": now, "exp": now + timedelta(minutes=5)}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def _request_with_cookies(**cookies) -> SimpleNamespace:
    # get_current_user는 request.cookies.get만 쓰므로 최소 stub으로 충분.
    return SimpleNamespace(cookies=cookies)


def test_access_token_roundtrip():
    assert decode_token(create_access_token(7), "access") == 7


def test_refresh_token_roundtrip():
    assert decode_token(create_refresh_token(42), "refresh") == 42


def test_type_mismatch_raises():
    access = create_access_token(7)
    with pytest.raises(AuthError):
        decode_token(access, "refresh")


def test_tampered_token_raises():
    with pytest.raises(AuthError):
        decode_token("not.a.jwt", "access")


def test_non_numeric_sub_raises_auth_error():
    # 서명은 유효하나 sub가 숫자가 아니면 int 변환 실패 → 500이 아니라 AuthError(401).
    with pytest.raises(AuthError):
        decode_token(_signed_token("abc"), "access")


async def test_optional_returns_none_when_sub_non_numeric():
    # optional 라우터는 비정상 토큰에서도 500이 아니라 guest(None)로 수렴해야 한다.
    request = _request_with_cookies(**{settings.access_cookie_name: _signed_token("abc")})
    assert await get_current_user_optional(request) is None


async def test_get_current_user_returns_id():
    request = _request_with_cookies(**{settings.access_cookie_name: create_access_token(9)})
    assert await get_current_user(request) == 9


async def test_get_current_user_missing_cookie_raises():
    with pytest.raises(AuthError):
        await get_current_user(_request_with_cookies())


async def test_optional_returns_none_when_missing():
    assert await get_current_user_optional(_request_with_cookies()) is None


async def test_optional_returns_none_when_invalid():
    request = _request_with_cookies(**{settings.access_cookie_name: "garbage"})
    assert await get_current_user_optional(request) is None


async def test_optional_returns_id_when_valid():
    request = _request_with_cookies(**{settings.access_cookie_name: create_access_token(5)})
    assert await get_current_user_optional(request) == 5
