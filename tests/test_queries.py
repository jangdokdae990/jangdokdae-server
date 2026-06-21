# 단독 실행: uv run pytest tests/test_queries.py -s
"""queries 단위 테스트 — 사용자 upsert race·LIKE 이스케이프·updated_at 갱신.

검증 방식: 실제 DB 없이 AsyncSession을 최소 stub으로 대체해 쿼리 함수의 제어 흐름만 본다.
검증 포인트:
- 동시 최초 로그인 race(IntegrityError)는 rollback 후 재조회로 정상 처리한다.
- 종목 검색 q의 LIKE 메타문자(\\,%,_)를 이스케이프한다.
- Core update는 ORM onupdate를 발화시키지 않으므로 updated_at을 명시적으로 SET한다.
"""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.queries import (
    _escape_like,
    get_or_create_user,
    replace_user_interests,
    update_last_login,
)


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _RaceDB:
    """첫 조회는 없음 → commit에서 unique 충돌 → rollback 후 재조회는 racing user."""

    def __init__(self, racing_user):
        self._racing_user = racing_user
        self.execute_calls = 0
        self.rolled_back = False

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _Result(None if self.execute_calls == 1 else self._racing_user)

    def add(self, _obj):
        pass

    async def commit(self):
        raise IntegrityError("INSERT", {}, Exception("duplicate provider account"))

    async def rollback(self):
        self.rolled_back = True

    async def refresh(self, _obj):
        pass


class _CaptureDB:
    """실행된 statement를 모아두는 stub — SET 절 검증용."""

    def __init__(self):
        self.statements = []

    async def execute(self, stmt):
        self.statements.append(stmt)
        return _Result(None)

    def add_all(self, _objs):
        pass

    async def commit(self):
        pass


async def test_get_or_create_user_handles_race():
    racing = SimpleNamespace(id=5, provider="kakao", provider_user_id="111")
    db = _RaceDB(racing)
    user, is_new = await get_or_create_user(db, "kakao", "111", None, None, None)
    assert user is racing
    assert is_new is False
    assert db.rolled_back is True  # 충돌 후 세션을 복구했다.


async def test_get_or_create_user_reraises_when_still_missing():
    # rollback 후에도 사용자가 없으면(진짜 다른 IntegrityError) 삼키지 않고 전파한다.
    db = _RaceDB(racing_user=None)
    with pytest.raises(IntegrityError):
        await get_or_create_user(db, "kakao", "111", None, None, None)


def test_escape_like_escapes_wildcards():
    assert _escape_like("a%b_c") == "a\\%b\\_c"


def test_escape_like_escapes_backslash_first():
    # 백슬래시를 먼저 치환해야 뒤에 붙는 이스케이프 백슬래시가 중복 처리되지 않는다.
    assert _escape_like("a\\b") == "a\\\\b"


async def test_update_last_login_sets_updated_at():
    db = _CaptureDB()
    await update_last_login(db, 1)
    assert any("updated_at" in str(stmt) for stmt in db.statements)


async def test_replace_user_interests_sets_updated_at():
    db = _CaptureDB()
    await replace_user_interests(db, 1, [1], [10], [100])
    update_stmts = [str(s) for s in db.statements if str(s).strip().upper().startswith("UPDATE")]
    assert update_stmts
    assert any("updated_at" in s for s in update_stmts)
