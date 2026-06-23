import os
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret")

import pytest

from app.api.models import BookmarkUpdateRequest, QuizSubmitRequest
from app.api.routers.issues import (
    _array_overlaps,
    _quiz_response,
    build_issue_detail,
    build_issue_list_item,
    get_issue_quiz,
    get_issue_quiz_result,
    mark_issue_read,
    submit_issue_quiz,
    update_issue_bookmark,
)
from app.db.orm_models.news_analysis import NewsAnalysis
from services.analyzer.quiz_generator import validate_quiz_output
from services.analyzer.schemas import QuizOutput, QuizQuestion


def test_build_issue_list_item_uses_docent_cluster_and_analysis():
    docent = SimpleNamespace(
        id=82,
        cluster_id=7,
        title="미국 기준금리 동결, 시장은 어떻게 반응할까?",
        hook_lines={"neutral": "연준의 동결 결정 이후 시장은 인하 시점을 보고 있습니다."},
        created_at=datetime(2026, 6, 22, 9, 30),
    )
    cluster = SimpleNamespace(size=3, importance=0.82)
    analysis = SimpleNamespace(
        frame="POLICY",
        scope="시장 전체",
        origin="해외",
        direction="중립",
        sector_tags=["시장·금리"],
        company_tags=[],
    )

    item = build_issue_list_item(docent, cluster, analysis)

    assert item.id == 82
    assert item.title == "미국 기준금리 동결, 시장은 어떻게 반응할까?"
    assert item.category == "시장·금리"
    assert item.teaser == "연준의 동결 결정 이후 시장은 인하 시점을 보고 있습니다."
    assert item.article_count == 3


def test_build_issue_detail_maps_content_heads_terms_and_sources():
    docent = SimpleNamespace(
        id=82,
        cluster_id=7,
        title="미국 기준금리 동결, 시장은 어떻게 반응할까?",
        hook_lines={},
        content_heads=[{"label": "무슨 일이에요", "answer": "연준이 기준금리를 동결했습니다."}],
        term_spans=[{"term": "기준금리", "sentence": "연준이 기준금리를 동결했습니다."}],
        created_at=datetime(2026, 6, 22, 9, 30),
    )
    cluster = SimpleNamespace(size=2, importance=0.82)
    analysis = SimpleNamespace(frame="POLICY", scope="시장 전체", sector_tags=[])
    articles = [
        SimpleNamespace(
            id=1,
            title="연준 기준금리 동결",
            url="https://example.com/fed",
            news_source="Reuters",
            published_at=datetime(2026, 6, 22, 8, 0),
        )
    ]

    detail = build_issue_detail(docent, cluster, analysis, articles)

    assert detail.cards[0].head == "무슨 일이에요"
    assert detail.cards[0].paragraphs == ["연준이 기준금리를 동결했습니다."]
    assert detail.terms[0].name == "기준금리"
    assert detail.terms[0].definition == "준비 중인 용어입니다."
    assert detail.sources[0].news_source == "Reuters"


def test_issue_array_filter_uses_postgres_overlap():
    sql = str(
        _array_overlaps(NewsAnalysis.sector_ids, [7]).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "&&" in sql


def _quizzes():
    return [
        {
            "quiz_id": "quiz-1",
            "kind": "term",
            "question": "기준금리는 무엇인가요?",
            "options": ["정책 금리", "개별 종목", "배당금", "거래량"],
            "answer_index": 0,
            "explanation": "기준금리는 중앙은행 정책 금리입니다.",
        },
        {
            "quiz_id": "quiz-2",
            "kind": "issue",
            "question": "이번 소식의 핵심은?",
            "options": ["동결", "상장폐지", "분할", "배당"],
            "answer_index": 0,
            "explanation": "연준이 금리를 동결한 소식입니다.",
        },
        {
            "quiz_id": "quiz-3",
            "kind": "domain",
            "question": "금리 동결은 보통 어디에 영향을 주나요?",
            "options": ["시장 심리", "상품명", "로고", "임원 취미"],
            "answer_index": 0,
            "explanation": "금리 전망은 시장 심리와 자금 흐름에 영향을 줍니다.",
        },
    ]


def test_quiz_response_hides_answer_and_explanation():
    body = _quiz_response(82, _quizzes())

    dumped = body.model_dump()
    assert dumped["quizzes"][0]["quiz_id"] == "quiz-1"
    assert "answer_index" not in dumped["quizzes"][0]
    assert "explanation" not in dumped["quizzes"][0]


@pytest.mark.asyncio
async def test_submit_issue_quiz_scores_answers():
    db = _QuizDB()

    result = await submit_issue_quiz(
        82,
        QuizSubmitRequest(answers={"quiz-1": 0, "quiz-2": 1, "quiz-3": 0}),
        db,
    )

    assert result.correct_count == 2
    assert result.total_count == 3
    assert result.results[1].answer_index == 0
    assert result.results[1].is_correct is False


@pytest.mark.asyncio
async def test_submit_issue_quiz_persists_authenticated_result():
    db = _QuizDB()

    await submit_issue_quiz(
        82,
        QuizSubmitRequest(answers={"quiz-1": 0, "quiz-2": 1, "quiz-3": 0}),
        db,
        user_id=7,
    )

    assert db.committed is True
    assert db.executed is True


@pytest.mark.asyncio
async def test_read_and_bookmark_mutations_are_persisted():
    db = _QuizDB()

    await mark_issue_read(82, user_id=7, db=db)
    await update_issue_bookmark(
        82,
        BookmarkUpdateRequest(bookmarked=True),
        user_id=7,
        db=db,
    )

    assert db.commit_count == 2


@pytest.mark.asyncio
async def test_get_saved_quiz_result_returns_latest_attempt():
    activity = SimpleNamespace(
        issue_docent_id=82,
        quiz_correct_count=2,
        quiz_total_count=3,
        quiz_completed_at=datetime(2026, 6, 23, 10, 5),
        quiz_results=[
            {
                "quiz_id": "quiz-1",
                "kind": "term",
                "selected_index": 0,
                "answer_index": 0,
                "is_correct": True,
                "explanation": "설명",
            }
        ],
    )

    result = await get_issue_quiz_result(82, user_id=7, db=_SavedQuizDB(activity))

    assert result.correct_count == 2
    assert result.results[0].quiz_id == "quiz-1"


@pytest.mark.asyncio
async def test_get_issue_quiz_not_ready_returns_404():
    with pytest.raises(Exception) as exc:
        await get_issue_quiz(82, _QuizDB(quizzes=[]))

    assert getattr(exc.value, "status_code", None) == 404


def test_quiz_output_requires_fixed_kind_order():
    output = QuizOutput(
        quizzes=[
            QuizQuestion(
                quiz_id="quiz-1",
                kind="issue",
                question="q",
                options=["a", "b", "c", "d"],
                answer_index=0,
                explanation="e",
            ),
            QuizQuestion(
                quiz_id="quiz-2",
                kind="term",
                question="q",
                options=["a", "b", "c", "d"],
                answer_index=0,
                explanation="e",
            ),
            QuizQuestion(
                quiz_id="quiz-3",
                kind="domain",
                question="q",
                options=["a", "b", "c", "d"],
                answer_index=0,
                explanation="e",
            ),
        ]
    )

    with pytest.raises(ValueError):
        validate_quiz_output(output)


class _QuizDB:
    def __init__(self, quizzes=None):
        self.row = SimpleNamespace(id=82, quizzes=_quizzes() if quizzes is None else quizzes)
        self.committed = False
        self.commit_count = 0
        self.executed = False

    async def get(self, _model, issue_id):
        return self.row if issue_id == 82 else None

    async def execute(self, _stmt):
        self.executed = True

    async def commit(self):
        self.committed = True
        self.commit_count += 1


class _SavedQuizDB:
    def __init__(self, activity):
        self.activity = activity

    async def scalar(self, _stmt):
        return self.activity
