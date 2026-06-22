"""스키마 공통 베이스 — 도메인별 스키마(auth.py, onboarding.py 등)는 이를 상속한다.

요청·응답 스키마 컨벤션:
- ORM 객체를 그대로 직렬화하는 응답은 ORMSchema(from_attributes=True)를 상속한다.
- 에러 응답은 app/core/errors.py 핸들러가 ErrorResponse 형태로 통일한다(문서화용 모델).
"""

from pydantic import BaseModel, ConfigDict


class ORMSchema(BaseModel):
    """ORM 객체 → 응답 직렬화용 베이스. SQLAlchemy 모델 속성을 그대로 읽는다."""

    model_config = ConfigDict(from_attributes=True)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """예외 핸들러 표준 응답 봉투 — OpenAPI 문서의 에러 응답 스키마로 재사용."""

    error: ErrorDetail
