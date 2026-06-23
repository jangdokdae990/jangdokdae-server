"""LLM 클라이언트 팩토리 — 분류(호출 A)·생성(호출 B)용 구조화 출력 체인.

두 호출 모두 Vertex AI gemini(ChatVertexAI)에 with_structured_output(Pydantic)을 씌워
JSON 파싱 오류를 제거한다(설계 10 §3). ADC 인증은 app.config._export_google_adc가 처리한다.
임베딩 클라이언트(services/embedder/embedding_client.py)의 모델·리전 분기와 같은 설정 출처를 쓴다.
"""

from __future__ import annotations

from langchain_google_vertexai import ChatVertexAI

from app.config import settings
from services.analyzer.schemas import ClassificationResult, ContentDraft, QuizOutput


def _chat(temperature: float) -> ChatVertexAI:
    """공통 ChatVertexAI 인스턴스. 프로젝트·리전·재시도는 settings에서 가져온다."""
    return ChatVertexAI(
        model=settings.vertex_model,
        project=settings.google_cloud_project or None,
        location=settings.google_cloud_location,
        temperature=temperature,
        max_retries=settings.llm_max_retries,
    )


def make_classifier():  # noqa: ANN201 — Runnable 제네릭 타입 노출은 과함
    """호출 A — 결정적 분류기. invoke(messages) → ClassificationResult."""
    return _chat(settings.classify_temperature).with_structured_output(ClassificationResult)


def make_generator():  # noqa: ANN201
    """호출 B — 본문 생성기. invoke(messages) → ContentDraft."""
    return _chat(settings.generate_temperature).with_structured_output(ContentDraft)


def make_quiz_generator():  # noqa: ANN201
    """호출 C — 퀴즈 생성기. invoke(messages) → QuizOutput."""
    return _chat(settings.generate_temperature).with_structured_output(QuizOutput)
