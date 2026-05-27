from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import auth, interests, news, users
from app.config import settings

app = FastAPI(
    title="장독대",
    description="주린이를 위한 주식 뉴스 큐레이션 & 학습 서비스",
    version="0.1.0"
)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 라우터 등록
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(news.router, prefix="/api/v1/news", tags=["news"])
app.include_router(interests.router, prefix="/api/v1/interests", tags=["interests"])


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
