# 단독 실행: uv run pytest tests/test_api_routers.py -s
"""마스터·온보딩·마이페이지 라우터 테스트 — DB 없이 라우터 로직만 검증.

검증 방식: TestClient + dependency 오버라이드(get_db·get_current_user)로 인증/세션을
대체하고, 라우터가 부르는 queries 함수를 monkeypatch해 DB 접근을 가른다. 검증·페이지네이션·
guest 허용·인증 가드 같은 라우터 자체 로직에 집중한다.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.security import get_current_user
from app.db.base import get_db
from app.main import app


def _company(company_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=company_id, stock_code=f"{company_id:06d}", name_ko=f"종목{company_id}",
        market="KOSPI", sector_id=10,
    )


@pytest.fixture
def client():
    # get_db는 쿼리 monkeypatch로 미사용 → None으로 대체. 인증은 user_id=1 고정.
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: 1
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def guest_client():
    # 인증 오버라이드 없음 → get_current_user_optional은 쿠키 없으면 None(guest).
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


# --- 마스터 조회 (guest 허용) ---


def test_markets_allow_guest(guest_client, monkeypatch):
    async def fake(_db):
        return [SimpleNamespace(id=3, code="KOSPI", name_ko="코스피", name_en="KOSPI")]

    monkeypatch.setattr("app.api.routers.masters.get_active_markets", fake)
    res = guest_client.get("/api/v1/markets")
    assert res.status_code == 200
    assert res.json()[0]["code"] == "KOSPI"


def test_companies_next_cursor_set_when_full_page(guest_client, monkeypatch):
    async def fake(_db, sector_id, market_code, q, limit, cursor):
        return [_company(i) for i in range(1, limit + 1)]  # 가득 찬 페이지

    monkeypatch.setattr("app.api.routers.masters.search_companies", fake)
    res = guest_client.get("/api/v1/companies?limit=3")
    body = res.json()
    assert len(body["items"]) == 3
    assert body["next_cursor"] == 3  # 마지막 id


def test_companies_next_cursor_none_when_partial_page(guest_client, monkeypatch):
    async def fake(_db, sector_id, market_code, q, limit, cursor):
        return [_company(1), _company(2)]  # limit보다 적음 → 마지막 페이지

    monkeypatch.setattr("app.api.routers.masters.search_companies", fake)
    res = guest_client.get("/api/v1/companies?limit=10")
    assert res.json()["next_cursor"] is None


def test_companies_limit_over_max_rejected(guest_client):
    assert guest_client.get("/api/v1/companies?limit=999").status_code == 422


# --- 온보딩 제출 (인증 필수) ---


def test_submit_interests_valid(client, monkeypatch):
    async def ids_market(_db, ids):
        return set(ids)

    async def ids_sector(_db, ids):
        return set(ids)

    async def ids_company(_db, ids):
        return set(ids)

    async def fake_replace(_db, user_id, market_ids, sector_ids, company_ids):
        return None

    monkeypatch.setattr("app.api.routers.onboarding.get_active_market_ids", ids_market)
    monkeypatch.setattr("app.api.routers.onboarding.get_existing_sector_ids", ids_sector)
    monkeypatch.setattr("app.api.routers.onboarding.get_active_company_ids", ids_company)
    monkeypatch.setattr("app.api.routers.onboarding.replace_user_interests", fake_replace)

    res = client.post(
        "/api/v1/onboarding/interests",
        json={"market_ids": [1], "sector_ids": [10], "company_ids": []},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "completed"


def test_submit_interests_invalid_market_id(client, monkeypatch):
    async def empty(_db, ids):
        return set()  # 제출 id가 활성 시장에 없음

    monkeypatch.setattr("app.api.routers.onboarding.get_active_market_ids", empty)
    res = client.post(
        "/api/v1/onboarding/interests",
        json={"market_ids": [999], "sector_ids": [10]},
    )
    assert res.status_code == 422


def test_submit_interests_fk_race_returns_422(client, monkeypatch):
    # 검증 통과 후 삽입 시점에 대상이 사라진 race(TOCTOU) → IntegrityError를 422로 변환.
    async def ids_ok(_db, ids):
        return set(ids)

    async def fake_replace(_db, user_id, market_ids, sector_ids, company_ids):
        raise IntegrityError("INSERT", {}, Exception("fk violation"))

    class _StubDB:
        async def rollback(self):  # 핸들러가 rollback 후 422를 던진다.
            return None

    app.dependency_overrides[get_db] = lambda: _StubDB()
    monkeypatch.setattr("app.api.routers.onboarding.get_active_market_ids", ids_ok)
    monkeypatch.setattr("app.api.routers.onboarding.get_existing_sector_ids", ids_ok)
    monkeypatch.setattr("app.api.routers.onboarding.get_active_company_ids", ids_ok)
    monkeypatch.setattr("app.api.routers.onboarding.replace_user_interests", fake_replace)

    res = client.post(
        "/api/v1/onboarding/interests",
        json={"market_ids": [1], "sector_ids": [10], "company_ids": [100]},
    )
    assert res.status_code == 422


def test_submit_interests_empty_sector_rejected(client):
    # 섹터 필수 — 빈 배열은 pydantic min_length로 차단.
    res = client.post(
        "/api/v1/onboarding/interests",
        json={"market_ids": [1], "sector_ids": []},
    )
    assert res.status_code == 422


def test_submit_interests_requires_auth(guest_client):
    # 인증 오버라이드 없음 → 쿠키 없으면 401.
    res = guest_client.post(
        "/api/v1/onboarding/interests",
        json={"market_ids": [1], "sector_ids": [10]},
    )
    assert res.status_code == 401


# --- 마이페이지 ---


def test_user_profile(client, monkeypatch):
    async def fake_user(_db, user_id):
        return SimpleNamespace(
            id=1, provider="kakao", email="a@k.com", nickname="카",
            profile_image_url="http://img", onboarding_completed_at=object(),
        )

    async def fake_interests(_db, user_id):
        return {"market_ids": [1], "sector_ids": [10], "company_ids": [100]}

    monkeypatch.setattr("app.api.routers.users.get_user_by_id", fake_user)
    monkeypatch.setattr("app.api.routers.users.get_user_interests", fake_interests)

    res = client.get("/api/v1/user/profile")
    body = res.json()
    assert res.status_code == 200
    assert body["onboarding_completed"] is True
    assert body["interests"]["sector_ids"] == [10]


def test_user_profile_requires_auth(guest_client):
    assert guest_client.get("/api/v1/user/profile").status_code == 401
