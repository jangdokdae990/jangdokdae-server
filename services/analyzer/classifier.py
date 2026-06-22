"""호출 A — 뉴스 이슈 분류기 (설계 10 §3).

이슈(대표 기사 본문 + 서브 헤드라인)를 scope×frame + origin·direction·태그로 분류한다.
프롬프트는 prompts/news_classify.yaml, 출력은 ClassificationResult(structured output).
"""

from __future__ import annotations

from typing import cast

from app.config import settings
from app.llm.chains import make_classifier
from app.llm.prompt_loader import load_prompt
from services.analyzer.schemas import ClassificationResult, Issue


def _format_sub_headlines(issue: Issue) -> str:
    if not issue.sub_articles:
        return "(없음)"
    return "\n".join(f"- {a.title}" for a in issue.sub_articles)


def needs_review(result: ClassificationResult, threshold: float | None = None) -> bool:
    """신뢰도가 임계값 미만이면 검수 큐 대상."""
    limit = settings.classification_confidence_threshold if threshold is None else threshold
    return result.confidence < limit


class NewsClassifier:
    """이슈 1건을 분류한다. classifier(LLM 체인)는 주입하거나 지연 생성한다(테스트 mock 용이)."""

    def __init__(self, classifier=None) -> None:
        self._classifier = classifier

    @property
    def classifier(self):  # noqa: ANN201
        if self._classifier is None:
            self._classifier = make_classifier()
        return self._classifier

    def classify(self, issue: Issue) -> ClassificationResult:
        prompt = load_prompt("news_classify")
        user = prompt["user_template"].format(
            main_title=issue.main_article.title,
            main_body=issue.main_article.body,
            sub_headlines=_format_sub_headlines(issue),
        )
        messages = [("system", prompt["system"]), ("human", user)]
        return cast(ClassificationResult, self.classifier.invoke(messages))
