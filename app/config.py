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
    # 임베딩 모델 — bake-off(2026-06-22) 선정: ko-sroberta(768)+title_body+HDBSCAN.
    # 결과: docs/evaluation/02~08. .env로 override 가능하나 기본값이 운영 정본.
    embed_model: str = "jhgan/ko-sroberta-multitask"
    embed_dim: int = 768
    embed_batch_size: int = 50
    chunk_size: int = 1000        # bake-off 최적(작은 청크는 본문 후반 희석으로 F1 하락)
    chunk_overlap: int = 200
    # 제목+본문 가중평균 결합 가중치 — α·제목 + (1-α)·본문(각 L2 정규화 후). bake-off 고정 0.3.
    embed_title_weight: float = 0.3
    cluster_min_cluster_size: int = 2
    cluster_min_samples: int = 1
    cluster_window_days: int = 14  # 이벤트 기반 재클러스터링 윈도우(최근 N일 전체 재계산)
    # 본문 fetch 운영 가드(설계 02 §8.4.1) — 임베딩 단계 본문 fetch의 전체 예산(초). 초과분은
    # title-only로 강제 전환해 파이프라인이 느린 매체에 묶이지 않게 한다.
    fetch_budget_seconds: int = 300
    dedup_similarity_threshold: float = 0.95  # bake-off 검증: same-이슈 7.3%·diff 오탐 0.01%
    top_issue_count: int = 10
    pipeline_window_hours: int = 24
    google_application_credentials: str = ""
    google_cloud_project: str = ""  # (.env: GOOGLE_CLOUD_PROJECT)
    google_cloud_location: str = "asia-northeast3"  # (.env: GOOGLE_CLOUD_LOCATION)
    # LLM 분석용 (.env: VERTEX_MODEL). 2026-06-22 정정: 3.5-flash는 리전 미존재(404).
    vertex_model: str = "gemini-2.5-flash"
    # 뉴스 분석·콘텐츠 생성 단계 (설계 10) — 분류·생성 LLM 호출 파라미터.
    # 분석할 상위 클러스터 수 (.env: ANALYSIS_TOP_CLUSTER_COUNT)
    analysis_top_cluster_count: int = 10
    classify_temperature: float = 0.0  # 호출 A(분류) — 결정적
    generate_temperature: float = 0.3  # 호출 B(생성) — 약간의 다양성
    classification_confidence_threshold: float = 0.5  # 미만이면 needs_review(검수 큐)
    llm_request_delay_seconds: float = 0.5  # 이슈 간 호출 간격(rate limit 완화)
    llm_max_retries: int = 6  # langchain(Vertex) 429 지수 백오프 재시도 횟수

    # --- 인증/세션 (httpOnly 쿠키 + stateless JWT) ---
    secret_key: str  # JWT 서명 키 — .env 필수, 코드 기본값 금지(시크릿)
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    access_cookie_name: str = "access_token"
    refresh_cookie_name: str = "refresh_token"
    cookie_secure: bool = False  # 운영(HTTPS)에서 True — 평문 전송 차단
    cookie_samesite: str = "lax"  # OAuth 리다이렉트 쿠키 전달 위해 strict 대신 lax
    cookie_domain: str | None = None

    # --- CORS / 프론트엔드 ---
    cors_origins: str = "http://localhost:3000"
    frontend_base_url: str = "http://localhost:3000"  # 로그인 완료·온보딩 redirect 대상

    # --- OAuth (client secret은 BE에만 보관, FE 번들 유입 금지) ---
    # redirect_uri는 provider 콘솔 등록값과 정확히 일치해야 함
    # (= {backend}/api/v1/auth/{provider}/callback)
    oauth_kakao_client_id: str = ""
    oauth_kakao_client_secret: str = ""
    oauth_kakao_redirect_uri: str = ""
    oauth_google_client_id: str = ""
    oauth_google_client_secret: str = ""
    oauth_google_redirect_uri: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        # CORSMiddleware는 origin 리스트를 받음 — 콤마 구분 env를 분리
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
