import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")

from scripts import backfill_quizzes


@pytest.mark.asyncio
async def test_backfill_commits_before_session_closes(monkeypatch, capsys):
    sessions = []

    class FakeSession:
        def __init__(self):
            self.active = False
            self.committed = False
            sessions.append(self)

        async def __aenter__(self):
            self.active = True
            return self

        async def __aexit__(self, *_args):
            self.active = False

        async def execute(self, _stmt):
            assert self.active

        async def commit(self):
            assert self.active
            self.committed = True

    async def fake_targets(_db, _issue_id, _limit, _force):
        return [(SimpleNamespace(id=1, cluster_id=10, title="테스트"), object())]

    class FakeGenerator:
        def generate(self, *_args):
            quiz = SimpleNamespace(model_dump=lambda: {"quiz_id": "q1"})
            return SimpleNamespace(quizzes=[quiz, quiz, quiz])

    monkeypatch.setattr(backfill_quizzes, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(backfill_quizzes, "_targets", fake_targets)
    monkeypatch.setattr(backfill_quizzes, "QuizGenerator", FakeGenerator)
    monkeypatch.setattr(backfill_quizzes, "_classification", lambda _row: object())
    monkeypatch.setattr(backfill_quizzes, "_content", lambda _row: object())

    await backfill_quizzes.run(issue_id=None, limit=1, dry_run=False, force=False)

    assert sessions[1].committed is True
    assert "done=1" in capsys.readouterr().out
