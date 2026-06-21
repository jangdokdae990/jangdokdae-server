"""환경 변수 기반 애플리케이션 설정."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "장독대"
    debug: bool = False
    database_url: str
    opendart_api_key: str = ""
    ecos_api_key: str = ""
    krx_id: str = ""
    krx_pw: str = ""
    embed_model: str = "jhgan/ko-sroberta-multitask"
    embed_dim: int = 768
    embed_batch_size: int = 50
    chunk_size: int = 1000
    chunk_overlap: int = 200
    cluster_min_cluster_size: int = 2
    cluster_min_samples: int = 1
    dedup_similarity_threshold: float = 0.95
    top_issue_count: int = 10
    pipeline_window_hours: int = 24
    google_application_credentials: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "asia-northeast3"
    vertex_model: str = "gemini-3.5-flash"

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


settings = Settings()  # type: ignore[call-arg]


def _export_google_adc() -> None:
    """표준 Google 환경변수를 os.environ으로 내보낸다.

    google-auth·Vertex SDK는 os.environ에서 직접 읽으므로 .env(settings) 값을 bridge한다.
    이미 셸에 설정돼 있으면 덮어쓰지 않는다.
    """
    if settings.google_application_credentials:
        # 상대 경로를 절대 경로로 — 실행 위치 무관하게 안정.
        key_path = Path(settings.google_application_credentials).resolve()
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(key_path))
    if settings.google_cloud_project:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
    if settings.google_cloud_location:
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)


def _export_krx_credentials() -> None:
    """pykrx가 os.environ에서 직접 읽는 KRX 로그인 자격을 bridge한다."""
    if settings.krx_id:
        os.environ.setdefault("KRX_ID", settings.krx_id)
    if settings.krx_pw:
        os.environ.setdefault("KRX_PW", settings.krx_pw)


_export_google_adc()
_export_krx_credentials()
