from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # 앱 설정
    APP_NAME: str = "장독대"
    DEBUG: bool = False

    # DB 설정
    DATABASE_URL: str

    # 인증 설정
    OAUTH_KAKAO_CLIENT_ID: str
    OAUTH_KAKAO_CLIENT_SECRET: str
    OAUTH_GOOGLE_CLIENT_ID: str
    OAUTH_GOOGLE_CLIENT_SECRET: str

    # JWT 설정
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # LLM 설정
    VERTEX_AI_PROJECT_ID: str
    VERTEX_AI_LOCATION: str = "asia-northeast1"
    VERTEX_AI_MODEL: str = "gemini-1.5-flash"

    # 임베딩 설정
    EMBED_MODEL: str = "jhgan/ko-sroberta-multitask"

    # 뉴스 수집 API
    NAVER_CLIENT_ID: str = ""
    NAVER_CLIENT_SECRET: str = ""
    FINNHUB_API_KEY: str = ""
    OPENDART_API_KEY: str = ""

    # CORS 설정
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
