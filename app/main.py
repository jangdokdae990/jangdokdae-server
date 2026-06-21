"""FastAPI 앱 부트스트랩 — 앱 생성, CORS, 예외 핸들러, 라우터 등록.

라우터 include는 각 도메인 라우터 구현 시점(섹션 1~10)에 추가한다.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, masters, onboarding, users
from app.config import settings
from app.core.errors import register_exception_handlers

API_V1_PREFIX = "/api/v1"


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, debug=settings.debug)

    # 쿠키 세션 기반 인증 → allow_credentials=True 필수(브라우저가 쿠키 동봉)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix=API_V1_PREFIX)
    app.include_router(masters.router, prefix=API_V1_PREFIX)
    app.include_router(onboarding.router, prefix=API_V1_PREFIX)
    app.include_router(users.router, prefix=API_V1_PREFIX)
    # TODO(섹션 9): 투자 성향 테스트 라우터(보류) include

    return app


app = create_app()
