"""인증 라우터 — OAuth 로그인/콜백, 세션 조회·갱신·로그아웃.

토큰 교환·세션 발급은 BE 전담(httpOnly 쿠키). state(CSRF)는 짧은 수명 쿠키로 검증한다.
"""

import secrets

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas.auth import InterestSummary, MeResponse
from app.config import settings
from app.core.errors import AuthError
from app.core.security import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    decode_token,
    delete_cookie,
    get_current_user,
    set_auth_cookies,
    set_cookie,
)
from app.db.base import get_db
from app.db.queries import (
    get_or_create_user,
    get_user_by_id,
    get_user_interests,
    update_last_login,
)
from services.auth.oauth_handler import get_oauth_handler

router = APIRouter(prefix="/auth", tags=["auth"])

# state(CSRF) 검증 쿠키 — authorize~callback 왕복 동안만 유지.
_STATE_COOKIE_NAME = "oauth_state"
_STATE_COOKIE_MAX_AGE = 300  # 5분
_ONBOARDING_PATH = "/onboarding"


@router.get("/{provider}/login")
async def login(provider: str) -> RedirectResponse:
    handler = get_oauth_handler(provider)  # 미지원 provider면 ValidationError(422)
    state = secrets.token_urlsafe(32)
    response = RedirectResponse(handler.build_authorize_url(state))
    # samesite=lax — provider에서 top-level redirect로 돌아올 때 쿠키가 전달돼야 함.
    set_cookie(response, _STATE_COOKIE_NAME, state, _STATE_COOKIE_MAX_AGE)
    return response


@router.get("/{provider}/callback")
async def callback(
    provider: str,
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if not code or not state:
        raise AuthError("인가 코드 또는 state가 없습니다")
    cookie_state = request.cookies.get(_STATE_COOKIE_NAME)
    if not cookie_state or cookie_state != state:
        raise AuthError("state 검증 실패(CSRF 의심)")

    handler = get_oauth_handler(provider)
    userinfo = await handler.authenticate(code, state)
    user, _is_new = await get_or_create_user(
        db,
        provider=userinfo.provider,
        provider_user_id=userinfo.provider_user_id,
        email=userinfo.email,
        nickname=userinfo.nickname,
        profile_image_url=userinfo.profile_image,
    )
    await update_last_login(db, user.id)

    # 온보딩 미완료 → 온보딩 경로, 완료 → 홈으로 redirect.
    target = settings.frontend_base_url
    if user.onboarding_completed_at is None:
        target = f"{settings.frontend_base_url}{_ONBOARDING_PATH}"
    response = RedirectResponse(target)
    set_auth_cookies(
        response, create_access_token(user.id), create_refresh_token(user.id)
    )
    delete_cookie(response, _STATE_COOKIE_NAME)
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    user_id: int = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    user = await get_user_by_id(db, user_id)
    if user is None:
        raise AuthError("사용자를 찾을 수 없습니다")
    interests = await get_user_interests(db, user_id)
    return MeResponse(
        id=user.id,
        provider=user.provider,
        email=user.email,
        nickname=user.nickname,
        profile_image_url=user.profile_image_url,
        onboarding_completed=user.onboarding_completed_at is not None,
        interests=InterestSummary(**interests),
    )


@router.post("/refresh")
async def refresh(
    request: Request, db: AsyncSession = Depends(get_db)
) -> Response:
    token = request.cookies.get(settings.refresh_cookie_name)
    if not token:
        raise AuthError("refresh 토큰이 없습니다")
    user_id = decode_token(token, "refresh")  # 만료·위조면 AuthError(401)
    # stateless JWT라 토큰만으로는 탈퇴 사용자를 막지 못함 — 존재 확인 후에만 회전한다.
    if await get_user_by_id(db, user_id) is None:
        raise AuthError("사용자를 찾을 수 없습니다")
    response: Response = JSONResponse({"status": "refreshed"})
    # access·refresh 동시 회전 — refresh 재사용 창을 줄인다.
    set_auth_cookies(
        response, create_access_token(user_id), create_refresh_token(user_id)
    )
    return response


@router.post("/logout")
async def logout() -> Response:
    response: Response = JSONResponse({"status": "logged_out"})
    clear_auth_cookies(response)
    return response
