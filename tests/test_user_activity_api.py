import os
from datetime import datetime
from types import SimpleNamespace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")

from app.api.routers.users import get_activity


@pytest.mark.asyncio
async def test_user_activity_returns_real_stats_and_records():
    read_at = datetime(2026, 6, 23, 10, 0)
    quiz_at = datetime(2026, 6, 23, 10, 5)
    activity = SimpleNamespace(
        issue_docent_id=82,
        read_at=read_at,
        bookmarked_at=read_at,
        quiz_correct_count=2,
        quiz_total_count=3,
        quiz_completed_at=quiz_at,
    )
    issue = SimpleNamespace(id=82, title="기준금리 동결")

    result = await get_activity(user_id=7, db=_ActivityDB([(activity, issue)]))

    assert result.stats.read_issue_count == 1
    assert result.stats.saved_issue_count == 1
    assert result.stats.completed_quiz_count == 1
    assert result.stats.correct_quiz_count == 2
    assert result.recent_issues[0].title == "기준금리 동결"
    assert result.quiz_records[0].quiz_correct_count == 2


class _ActivityDB:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _stmt):
        return self

    def all(self):
        return self.rows
