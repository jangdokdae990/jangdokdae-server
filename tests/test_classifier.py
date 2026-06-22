"""classifier 단위 테스트 — 분류 호출·신뢰도 검수 큐 (설계 10 §3)."""

from app.config import settings
from services.analyzer.classifier import (
    NewsClassifier,
    _format_sub_headlines,
    needs_review,
)
from services.analyzer.schemas import (
    Article,
    ClassificationResult,
    CompanyTag,
    Issue,
)


class _FakeChain:
    def __init__(self, result):
        self._result = result
        self.last_messages = None

    def invoke(self, messages):
        self.last_messages = messages
        return self._result


def _result(confidence: float) -> ClassificationResult:
    return ClassificationResult(
        scope_reasoning="r",
        scope="회사",
        frame_reasoning="r",
        frame="EARNINGS",
        origin="국내",
        direction="상승",
        confidence=confidence,
        evidence="e",
        company_tags=[CompanyTag(name="삼성전자", role="primary")],
    )


def _issue() -> Issue:
    return Issue(
        cluster_id=1,
        main_article=Article(title="제목", body="본문", url="u"),
        sub_articles=[Article(title="서브1"), Article(title="서브2")],
    )


def test_needs_review_below_threshold():
    assert needs_review(_result(0.3)) is True
    assert needs_review(_result(0.9)) is False
    # 임계값 직접 지정.
    assert needs_review(_result(0.6), threshold=0.7) is True


def test_default_threshold_matches_settings():
    boundary = settings.classification_confidence_threshold
    assert needs_review(_result(boundary)) is False  # 임계값 이상은 통과
    assert needs_review(_result(boundary - 0.01)) is True


def test_format_sub_headlines():
    issue = _issue()
    text = _format_sub_headlines(issue)
    assert "- 서브1" in text and "- 서브2" in text
    empty = _format_sub_headlines(
        Issue(cluster_id=1, main_article=Article(title="t"), sub_articles=[])
    )
    assert empty == "(없음)"


def test_classify_returns_result_and_formats_prompt():
    clf = NewsClassifier(classifier=_FakeChain(_result(0.9)))
    result = clf.classify(_issue())
    assert result.frame == "EARNINGS"
    human_msg = clf.classifier.last_messages[1][1]
    assert "제목" in human_msg
    assert "서브1" in human_msg
