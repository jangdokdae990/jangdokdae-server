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
    krx_id: str = ""  # KRX 로그인 ID (.env: KRX_ID) — pykrx KOSPI200·섹터 조회용
    krx_pw: str = ""  # KRX 로그인 PW (.env: KRX_PW)
    # 임베딩 차원은 모델에 따라 바뀌므로(768 vs 1024) 환경 변수로 분리한다.
    embed_model: str = "jhgan/ko-sroberta-multitask"  # baseline (.env: EMBED_MODEL)
    embed_dim: int = 768  # 임베딩 차원 (.env: EMBED_DIM) — 모델에 따라 768 또는 1024
    embed_batch_size: int = 50  # Vertex AI 최대 허용 배치 크기
    # 클러스터링·중복·이슈 선정 파라미터 — 실데이터 교정 시 조정하도록 환경 변수로 둔다.
    cluster_min_cluster_size: int = 2  # HDBSCAN min_cluster_size (.env: CLUSTER_MIN_CLUSTER_SIZE)
    cluster_min_samples: int = 1  # HDBSCAN min_samples — noise 최소·싱글톤 보존
    dedup_similarity_threshold: float = 0.95  # 근접 중복 soft flag 임계값
    top_issue_count: int = 10  # 분석 파이프라인에 넘길 최대 이슈 수
    # "당일 수집분" 처리 창(시간) — dedup·클러스터링이 같은 창을 공유한다.
    pipeline_window_hours: int = 24
    # Google Cloud / Vertex AI — gemini 임베딩 + LLM 분석에서 사용. 서비스 계정 키 경로.
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
