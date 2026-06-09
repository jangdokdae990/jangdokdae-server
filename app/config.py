"""환경 변수 기반 애플리케이션 설정."""

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
    # Vertex AI — gemini 계열 임베딩(관리형) 분기에서 사용. 프로젝트/리전이 없으면 Vertex 호출 불가.
    # HuggingFace 분기(KURE·ko-sroberta)는 이 값들이 비어 있어도 동작한다.
    vertex_ai_project_id: str = ""  # (.env: VERTEX_AI_PROJECT_ID)
    vertex_ai_location: str = "asia-northeast1"  # (.env: VERTEX_AI_LOCATION)
    vertex_ai_model: str = "gemini-1.5-flash"  # LLM 분석용 (.env: VERTEX_AI_MODEL)

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
