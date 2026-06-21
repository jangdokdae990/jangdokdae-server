"""JWT 발급·검증, httpOnly 세션 쿠키 set/clear, 인증 의존성.

세션은 stateless JWT(서버 저장 없음) — access는 쿠키, refresh도 쿠키로 회전한다.
client secret·토큰은 BE만 다루고 FE는 쿠키를 직접 읽지 않는다(httpOnly).

섹션 0 범위: get_current_user는 토큰 검증 후 user_id(int)만 반환한다.
실제 User 조회는 User 모델 신설(섹션 5) 후 연결한다.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal, cast

from fastapi import Request, Response
from jose import JWTError, jwt

from app.config import settings
from app.core.errors import AuthError

TokenType = Literal["access", "refresh"]
SameSite = Literal["lax", "strict", "none"]


def _create_token(user_id: int, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),  # JWT 표준상 sub는 문자열
        "type": token_type,  # access/refresh 혼용 차단용
        "iat": now,
        "exp": now + expires_delta,
    }
    token: str = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token


def create_access_token(user_id: int) -> str:
    return _create_token(
        user_id, "access", timedelta(minutes=settings.access_token_expire_minutes)
    )


def create_refresh_token(user_id: int) -> str:
    return _create_token(
        user_id, "refresh", timedelta(days=settings.refresh_token_expire_days)
    )


def decode_token(token: str, expected_type: TokenType) -> int:
    """토큰 검증 후 user_id 반환. 서명·만료·타입 불일치는 AuthError."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    except JWTError as exc:
        raise AuthError("유효하지 않거나 만료된 토큰입니다") from exc
    if payload.get("type") != expected_type:
        raise AuthError("토큰 유형이 올바르지 않습니다")
    subject = payload.get("sub")
    if subject is None:
        raise AuthError("토큰에 사용자 정보가 없습니다")
    try:
        return int(subject)
    except (TypeError, ValueError) as exc:
        # sub가 숫자가 아니면(비정상·변조 토큰) 500 대신 401로 일관 처리
        raise AuthError("토큰에 사용자 정보가 없습니다") from exc


def set_cookie(response: Response, key: str, value: str, max_age: int) -> None:
    """쿠키 보안 정책 단일 소스 — 모든 세션·state 쿠키가 같은 속성으로 설정되게 한다."""
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=cast(SameSite, settings.cookie_samesite),
        domain=settings.cookie_domain,
        path="/",
    )


def delete_cookie(response: Response, key: str) -> None:
    """set_cookie와 동일한 domain·path로 삭제 — 속성이 어긋나면 삭제가 안 먹는다."""
    response.delete_cookie(key=key, domain=settings.cookie_domain, path="/")


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """access·refresh를 httpOnly 쿠키로 심는다. max_age는 만료와 동일하게 맞춘다."""
    set_cookie(
        response,
        settings.access_cookie_name,
        access_token,
        settings.access_token_expire_minutes * 60,
    )
    set_cookie(
        response,
        settings.refresh_cookie_name,
        refresh_token,
        settings.refresh_token_expire_days * 24 * 60 * 60,
    )


def clear_auth_cookies(response: Response) -> None:
    delete_cookie(response, settings.access_cookie_name)
    delete_cookie(response, settings.refresh_cookie_name)


async def get_current_user(request: Request) -> int:
    """access 쿠키 검증 후 user_id 반환. 비인증이면 AuthError(401) — 보호 라우터용."""
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise AuthError("로그인이 필요합니다")
    return decode_token(token, "access")


async def get_current_user_optional(request: Request) -> int | None:
    """guest 허용 — access 쿠키가 없거나 유효하지 않으면 None(공개 라우터용)."""
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        return None
    try:
        return decode_token(token, "access")
    except AuthError:
        return None
