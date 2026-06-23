# 장독대 (JANGDOKDAE)

> **시장 독해를 대신해 드립니다** — 주식 시장·뉴스를 쉽게 풀어주고, 스스로 판단하도록 돕는 주린이 독해 보조 서비스

## 프로젝트 개요

읽어도 모르는 시장 뉴스를, 주린이가 이해하는 언어로 번역하는 AI 서비스입니다. 단순 요약·시세 알림이 아니라 어려운 뉴스를 LLM으로 해설하고, **모든 해설에 1차 정보 출처·신뢰 시그널**을 붙여 초보자가 믿고 학습하며 스스로 판단하도록 돕습니다.

- **타깃** — 2030 · 투자 경력 2년 미만 · 경제 용어 절반 이하 이해 · 뉴스·공시를 스스로 못 읽어 2차 가공물(유튜브·리딩방)에 의존하는 주린이
- **핵심 가치** — 쉽게(독해) · 믿게(출처·검증) · 배우게(용어풀이·퀴즈)

## 기술 스택

| 분류 | 사용 기술 |
| --- | --- |
| 백엔드 | Python 3.12, FastAPI, uvicorn, uv |
| 데이터베이스 | PostgreSQL (Neon), pgvector, SQLAlchemy, Alembic |
| LLM | Vertex AI (Gemini), LangChain 1.x, LangGraph 1.x, langchain-google-vertexai |
| 임베딩·클러스터링 | sentence-transformers (ko-sroberta), HDBSCAN, scikit-learn |
| 인증 | OAuth 2.0 (카카오·구글), JWT (python-jose) |
| 오케스트레이션 | Apache Airflow (ExternalPythonOperator), Docker / docker-compose |
| 데이터 수집 | feedparser, trafilatura, FinanceDataReader, pykrx, OpenDART, ECOS |

## 아키텍처: L1 / L2 2계층

파이프라인을 **"흐름을 LLM이 판단하는가"** 기준으로 두 계층으로 나눕니다.

- **L1 (정형 파이프라인)** — 수집 → 전처리 → 임베딩 → 클러스터링. 결정적 흐름이라 Airflow가 Task별 격리·재시도로 오케스트레이션합니다.
- **L2 (추론 파이프라인)** — 분류 → 콘텐츠 생성 → 발행. LLM이 흐름을 판단하므로 LangGraph 에이전트가 담당합니다.

```text
수집 → 전처리(중복 제거) → 임베딩 → 클러스터링 → scope×frame 분류 → 콘텐츠 생성 → Issue Docent 발행
└──────────────────── L1 (Airflow) ────────────────────┘ └──────────── L2 (LangGraph) ────────────┘
```

레이어는 단방향으로 의존합니다: `app/api` → `services` → `app/db` · `app/llm`.

## 프로젝트 구조

```text
app/                       # FastAPI 애플리케이션
├── main.py                # 앱 생성, 라우터 등록
├── config.py              # 환경 변수 (pydantic-settings)
├── api/
│   ├── schemas/           # Pydantic 요청/응답 스키마
│   └── routers/           # auth, masters, onboarding, users, issues, dictionary
├── core/                  # security(JWT), errors
├── db/
│   ├── orm_models/        # SQLAlchemy ORM (도메인별 파일)
│   └── queries.py         # DB 쿼리 함수
└── llm/                   # LangChain 체인, LangGraph 그래프, 프롬프트 로더

services/                  # 비즈니스 로직 (행위자 명사 -er/-or)
├── collector/             # RSS·종목·공시·재무·거시 수집기
├── preprocessor/          # 중복 제거·본문 처리
├── embedder/              # 임베딩·클러스터링·중요도 스코어
├── analyzer/              # 분류·콘텐츠/용어/퀴즈 생성·보강
├── monitor/               # SPOF 모니터
├── pipeline/              # 로컬 1회 완주 러너
└── auth/                  # 카카오·구글 OAuth

dags/                      # Airflow DAG
prompts/                   # LLM 프롬프트 (YAML)
scripts/                   # 백필·동기화·실험 비교 스크립트
evaluation/                # 임베딩/클러스터링 bake-off·지표
docs/                      # 설계·규칙·가이드 문서
```

## 빠른 시작

```bash
cp .env.example .env           # 환경 변수 설정
uv sync                        # 의존성 설치
alembic upgrade head           # DB 마이그레이션 적용
uvicorn app.main:app --reload  # 개발 서버 (http://localhost:8000)
```

API 문서(Swagger): <http://localhost:8000/docs>

## 파이프라인 실행

```bash
# 로컬 1회 완주 (수집 → 임베딩·클러스터링 → 분석) — 테스트용, 부분 실패 시 전체 중단
python -m services.pipeline.runner

# 분석 단계만 단독 실행
python scripts/run_analysis.py

# 운영: Airflow가 Task별 격리·재시도 담당
docker compose up -d
```

### Airflow DAG

| DAG | 스케줄 | 역할 |
| --- | --- | --- |
| `jangdokdae_pipeline` | 장 세션 기반 | 뉴스·종목 수집 → 전처리 → 임베딩 |
| `jangdokdae_clustering` | 임베딩 완료 이벤트(Asset) | 재클러스터링 → 분석 → 콘텐츠 생성 |
| `jangdokdae_macro` | 매월 1일 16:00 KST | 거시 지표 수집 |
| `jangdokdae_quarterly` | 분기 1일 09:00 KST | 분기 재무·공시 갱신 |

> Airflow는 앱 전용 venv(`/home/airflow/jangdokdae-venv`)에서 `ExternalPythonOperator`로 단계를 실행합니다(앱 의존성과 Airflow 의존성 분리). 자세한 건 [`docs/design/00-workflow-airflow.md`](docs/design/00-workflow-airflow.md).

## API 엔드포인트

모든 경로는 `/api/v1` 프리픽스를 가집니다.

- **auth** — 카카오·구글 OAuth 로그인, 토큰 갱신/로그아웃
- **onboarding** — 관심 시장·섹터·종목 등록
- **users** — 내 정보 조회/수정
- **masters** — 시장·섹터·종목 마스터 조회
- **issues** — 오늘의 이슈 피드(개인화), 이슈 상세(해설·출처·퀴즈)
- **dictionary** — 용어 사전 조회

## 데이터 파이프라인 상세

1. **수집** — YAML 피드 레지스트리 기반 국내외 경제·증권 RSS. 본문은 trafilatura로 fetch해 처리 후 **즉시 폐기**(저작권 가드), 메타데이터만 저장.
2. **전처리** — GUID 정확 중복 제거 + 다층 유사도 + 전재 매체 수(reprint count) 보존.
3. **임베딩·클러스터링** — 제목·본문 가중평균 임베딩(ko-sroberta) → HDBSCAN. 최근 N일 윈도우 이벤트 기반 재클러스터링, cluster id 멤버 승계.
4. **분류** — scope(3) × frame(7) + origin·direction flag, `with_structured_output`.
5. **콘텐츠 생성** — 4-head 학습형 콘텐츠, 용어풀이(사전 기반)·전문가 시각·퀴즈, Issue Docent 영속화 + 관심사 태깅.
6. **품질 게이트** — honest-blank·본문 부족 콘텐츠는 `needs_review`로 격리, term_spans는 본문 등장 용어만 보존(할루시네이션 억제).

## 테스트 · 코드 품질

```bash
pytest                 # 전체 테스트
pytest --cov=app       # 커버리지 포함

ruff check .           # 린트
black .                # 포매팅
mypy app/              # 타입 체크
```

## 환경 변수

`.env.example`을 복사해 설정합니다. 주요 항목:

```env
DATABASE_URL=postgresql://...           # Neon PostgreSQL
SECRET_KEY=...                          # JWT 서명 키
OAUTH_KAKAO_CLIENT_ID=...               # 카카오 OAuth
OAUTH_GOOGLE_CLIENT_ID=...              # 구글 OAuth
GOOGLE_APPLICATION_CREDENTIALS=...      # Vertex AI 서비스 계정
GOOGLE_CLOUD_PROJECT=...                # GCP 프로젝트
VERTEX_MODEL=...                        # Gemini 모델 ID
OPENDART_API_KEY=...                    # 공시(DART)
ECOS_API_KEY=...                        # 한국은행 거시 지표
EMBED_MODEL=...                         # 임베딩 모델
EMBED_TITLE_WEIGHT=...                  # 제목 가중치(α)
CLUSTER_WINDOW_DAYS=...                 # 재클러스터링 윈도우
```

전체 목록은 [`.env.example`](.env.example) 참고.

## 참고 문서

- [`docs/rules/architecture.md`](docs/rules/architecture.md) — 폴더 구조 및 레이어
- [`docs/rules/conventions.md`](docs/rules/conventions.md) — 파일명/클래스명/함수명 규칙
- [`docs/rules/API_SPEC.md`](docs/rules/API_SPEC.md) — API 명세
- [`docs/design/`](docs/design/) — 단계별 설계 문서(수집·임베딩·분석·콘텐츠·품질 게이트)
- [`docs/guide/`](docs/guide/) — Airflow·Docker 운영 가이드
