"""환경 변수 기반 애플리케이션 설정."""

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "장독대"
    debug: bool = False
    database_url: str  # .env의 Neon 기본형 URL (postgresql://...?sslmode=require)
    opendart_api_key: str = ""  # DART 공시 API 키 (.env: OPENDART_API_KEY)
    ecos_api_key: str = ""  # 한국은행 ECOS 거시지표 API 키 (.env: ECOS_API_KEY)
    # 임베딩 모델은 미확정 — 후보 비교 테스트 후 확정(설계 05 §11). 모델 변경 시 차원이
    # 바뀔 수 있어(768 절단 vs 1024) 차원을 환경 변수로 분리한다. ORM Vector(...)·마이그레이션이
    # 이 값을 단일 출처로 참조하도록 점진 정리한다.
    embed_model: str = "jhgan/ko-sroberta-multitask"  # baseline (.env: EMBED_MODEL)
    embed_dim: int = 768  # 임베딩 차원 (.env: EMBED_DIM) — 모델에 따라 768 또는 1024
    embed_batch_size: int = 50  # Vertex AI 최대 허용 배치 크기 (설계 05 §2.3)
    # Google Cloud / Vertex AI — gemini 계열 임베딩(관리형) 분기 + LLM 분석에서 사용.
    # 프로젝트가 없으면 Vertex 호출 불가. HuggingFace 분기(KURE·ko-sroberta)는 비어 있어도 동작한다.
    # 서비스 계정 키 경로 (.env: GOOGLE_APPLICATION_CREDENTIALS)
    google_application_credentials: str = ""
    google_cloud_project: str = ""  # (.env: GOOGLE_CLOUD_PROJECT)
    google_cloud_location: str = "asia-northeast3"  # (.env: GOOGLE_CLOUD_LOCATION)
    vertex_model: str = "gemini-2.5-flash"  # LLM 분석용 (.env: VERTEX_MODEL)

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


def _export_google_adc() -> None:
    """표준 Google 환경변수를 os.environ으로 내보낸다.

    pydantic-settings는 .env를 settings 객체로만 읽고 os.environ엔 넣지 않는다. 반면
    google-auth(ADC)·Vertex SDK는 os.environ의 GOOGLE_APPLICATION_CREDENTIALS 등을 직접
    읽으므로, 여기서 한 번 bridge 해줘야 gemini 임베딩·LLM이 서비스 계정으로 인증된다.
    이미 셸에 설정돼 있으면(setdefault) 덮어쓰지 않는다.
    """
    if settings.google_application_credentials:
        # 상대 경로(.env: credentials/vertex_key.json)를 절대 경로로 — 실행 위치 무관하게 안정.
        key_path = Path(settings.google_application_credentials).resolve()
        os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(key_path))
    if settings.google_cloud_project:
        os.environ.setdefault("GOOGLE_CLOUD_PROJECT", settings.google_cloud_project)
    if settings.google_cloud_location:
        os.environ.setdefault("GOOGLE_CLOUD_LOCATION", settings.google_cloud_location)


_export_google_adc()
