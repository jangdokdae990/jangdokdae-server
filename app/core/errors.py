"""도메인 예외 + FastAPI 예외 핸들러 표준화.

라우터·서비스는 HTTPException 대신 도메인 예외를 던지고, 응답 직렬화는 핸들러가 전담한다.
응답 봉투는 항상 {"error": {"code", "message"}} 형태로 통일한다(FE 파싱 단순화).
"""

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    """모든 도메인 예외의 베이스. status_code·code(머신용)·message(사람용)를 표준화한다."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.code
        super().__init__(self.message)


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


def _envelope(code: str, message: str) -> dict[str, dict[str, str]]:
    return {"error": {"code": code, "message": message}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        # 4xx는 클라이언트 입력 문제 → info, 5xx는 서버 결함 → exception(스택 포함)
        if exc.status_code >= 500:
            logger.exception("도메인 예외(서버): %s", exc.code)
        else:
            logger.info("도메인 예외: %s %s", exc.code, exc.message)
        return JSONResponse(
            status_code=exc.status_code, content=_envelope(exc.code, exc.message)
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422, content=_envelope("validation_error", str(exc.errors()))
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 라우팅 404 등 프레임워크 발생 HTTPException도 같은 봉투로 통일
        return JSONResponse(
            status_code=exc.status_code, content=_envelope("http_error", str(exc.detail))
        )
