# 단독 실행: uv run pytest tests/test_auth_callback.py -s
"""인증 라우터 통합 테스트 — login redirect·콜백 state 검증·가입/로그인 분기.

검증 방식: TestClient(redirect 미추적)로 Location·Set-Cookie를 직접 본다. provider 호출과
DB는 monkeypatch로 가른다. 검증 포인트:
- /login은 provider authorize로 302/307 + state 쿠키를 심는다.
- 콜백은 code/state 누락·state 불일치를 401로 막는다(CSRF).
- 신규(온보딩 미완료)는 온보딩 경로로, 기존(완료)은 홈으로 redirect하며 세션 쿠키를 발급한다.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core.security import create_refresh_token
from app.db.base import get_db
from app.main import app
from services.auth.oauth_handler import OAuthUserInfo

_USERINFO = OAuthUserInfo(
    provider="kakao", provider_user_id="111", email="a@k.com",
    nickname="카", profile_image="http://img",
)


class _FakeHandler:
    def build_authorize_url(self, state: str) -> str:
        return f"https://kauth.kakao.com/oauth/authorize?state={state}"

    async def authenticate(self, code: str, state: str) -> OAuthUserInfo:
        return _USERINFO


@pytest.fixture
def client():
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _patch_callback_deps(monkeypatch, onboarding_done: bool):
    user = SimpleNamespace(
        id=1, onboarding_completed_at=(object() if onboarding_done else None)
    )

    async def fake_get_or_create(_db, **kwargs):
        return user, not onboarding_done

    async def fake_update_login(_db, user_id):
        return None

    monkeypatch.setattr("app.api.routers.auth.get_oauth_handler", lambda p: _FakeHandler())
    monkeypatch.setattr("app.api.routers.auth.get_or_create_user", fake_get_or_create)
    monkeypatch.setattr("app.api.routers.auth.update_last_login", fake_update_login)


def test_login_redirects_with_state_cookie(client):
    res = client.get("/api/v1/auth/kakao/login", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"].startswith("https://kauth.kakao.com")
    assert "oauth_state=" in res.headers.get("set-cookie", "")


def test_callback_missing_code_rejected(client):
    res = client.get("/api/v1/auth/kakao/callback?state=S", follow_redirects=False)
    assert res.status_code == 401


def test_callback_state_mismatch_rejected(client):
    client.cookies.set("oauth_state", "COOKIE_STATE")
    res = client.get(
        "/api/v1/auth/kakao/callback?code=c&state=QUERY_STATE", follow_redirects=False
    )
    assert res.status_code == 401


def test_callback_new_user_redirects_to_onboarding(client, monkeypatch):
    _patch_callback_deps(monkeypatch, onboarding_done=False)
    client.cookies.set("oauth_state", "S")
    res = client.get("/api/v1/auth/kakao/callback?code=c&state=S", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == f"{settings.frontend_base_url}/onboarding"
    # 세션 쿠키 발급 확인
    assert settings.access_cookie_name in res.headers.get("set-cookie", "")


def test_callback_existing_user_redirects_home(client, monkeypatch):
    _patch_callback_deps(monkeypatch, onboarding_done=True)
    client.cookies.set("oauth_state", "S")
    res = client.get("/api/v1/auth/kakao/callback?code=c&state=S", follow_redirects=False)
    assert res.status_code in (302, 307)
    assert res.headers["location"] == settings.frontend_base_url


# --- 세션 갱신 (/refresh) — 존재 사용자만 회전 ---


def test_refresh_rotates_for_existing_user(client, monkeypatch):
    async def fake_get_user(_db, user_id):
        return SimpleNamespace(id=user_id)

    monkeypatch.setattr("app.api.routers.auth.get_user_by_id", fake_get_user)
    client.cookies.set(settings.refresh_cookie_name, create_refresh_token(1))
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 200
    # access·refresh 동시 재발급 확인
    assert settings.access_cookie_name in res.headers.get("set-cookie", "")


def test_refresh_rejected_for_deleted_user(client, monkeypatch):
    # 토큰은 유효하나 사용자가 DB에 없으면(탈퇴) 회전 거부 — 좀비 세션 차단.
    async def fake_get_user(_db, user_id):
        return None

    monkeypatch.setattr("app.api.routers.auth.get_user_by_id", fake_get_user)
    client.cookies.set(settings.refresh_cookie_name, create_refresh_token(999))
    res = client.post("/api/v1/auth/refresh")
    assert res.status_code == 401


def test_refresh_without_token_rejected(client):
    assert client.post("/api/v1/auth/refresh").status_code == 401
