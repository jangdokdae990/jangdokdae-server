"""호출 C — issue_docent 퀴즈 생성기.

기존 v1 계약을 유지하되 term/issue/domain 3문항 고정으로 확장한다.
"""

from __future__ import annotations

from app.llm.chains import make_quiz_generator
from services.analyzer.schemas import ClassificationResult, ContentResult, Issue, QuizOutput

_EXPECTED_KINDS = ["term", "issue", "domain"]


def validate_quiz_output(output: QuizOutput) -> QuizOutput:
    kinds = [quiz.kind for quiz in output.quizzes]
    ids = [quiz.quiz_id for quiz in output.quizzes]
    if kinds != _EXPECTED_KINDS:
        raise ValueError(f"quiz kinds must be {_EXPECTED_KINDS}, got {kinds}")
    if ids != ["quiz-1", "quiz-2", "quiz-3"]:
        raise ValueError(f"quiz ids must be quiz-1..quiz-3, got {ids}")
    return output


def _heads_text(content: ContentResult) -> str:
    return "\n".join(
        f"- {head.label}: {head.question}\n  {head.answer}" for head in content.heads
    )


def _terms_text(content: ContentResult, classification: ClassificationResult) -> str:
    terms = [span.term for span in content.term_spans] or classification.term_tags
    return ", ".join(dict.fromkeys(t for t in terms if t)) or "(없음)"


def _domain_text(classification: ClassificationResult) -> str:
    companies = [tag.name for tag in classification.company_tags]
    sectors = classification.sector_tags
    return f"섹터: {', '.join(sectors) or '(없음)'} / 기업: {', '.join(companies) or '(없음)'}"


class QuizGenerator:
    def __init__(self, generator=None) -> None:
        self._generator = generator

    @property
    def generator(self):  # noqa: ANN201
        if self._generator is None:
            self._generator = make_quiz_generator()
        return self._generator

    def generate(
        self,
        issue: Issue,
        classification: ClassificationResult,
        content: ContentResult,
    ) -> QuizOutput:
        system = (
            "너는 초보 투자자가 방금 읽은 뉴스 해설을 이해했는지 확인하는 퀴즈 출제자다. "
            "투자 조언, 매수/매도 판단, 수혜주 찍기, 주가 예측을 금지한다."
        )
        user = (
            "아래 콘텐츠만 근거로 4지선다 퀴즈를 정확히 3개 만든다.\n"
            '순서와 kind는 고정이다: quiz-1 term, quiz-2 issue, quiz-3 domain.\n'
            "answer_index는 0부터 시작한다.\n\n"
            f"[뉴스 제목]\n{issue.main_article.title}\n\n"
            "[분류]\n"
            f"{classification.scope} / {classification.frame} / "
            f"{classification.origin} / {classification.direction}\n"
            f"[용어 후보]\n{_terms_text(content, classification)}\n"
            f"[도메인 힌트]\n{_domain_text(classification)}\n\n"
            f"[본문]\n{_heads_text(content)}"
        )
        return validate_quiz_output(self.generator.invoke([("system", system), ("human", user)]))
