"""환경 변수 기반 애플리케이션 설정."""

from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "장독대"
    debug: bool = False
    database_url: str  # .env의 Neon 기본형 URL (postgresql://...?sslmode=require)

    @property
    def async_url(self) -> str:
        # asyncpg는 sslmode 등 쿼리 파라미터를 모름 → 제거하고 SSL은 connect_args로 전달
        parts = urlsplit(self.database_url)
        return urlunsplit(("postgresql+asyncpg", parts.netloc, parts.path, "", ""))

    @property
    def sync_url(self) -> str:
        # Alembic용 sync 드라이버. psycopg2는 sslmode 쿼리를 그대로 처리
        parts = urlsplit(self.database_url)
        return urlunsplit(
            ("postgresql+psycopg2", parts.netloc, parts.path, parts.query, parts.fragment)
        )


settings = Settings()  # type: ignore[call-arg]  # database_url은 .env에서 로드
