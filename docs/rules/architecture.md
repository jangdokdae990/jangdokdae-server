# 장독대 서버 아키텍처

> **작성자** Kim minkyoung · **작성일** 2026-05-27

## 전체 구조

```
jangdokdae-server/
├── app/                    # FastAPI 애플리케이션
│   ├── api/                # HTTP 인터페이스 레이어
│   ├── core/               # 인증, 에러 등 공통 기능
│   ├── db/                 # 데이터베이스 레이어
│   └── llm/                # LangChain / LangGraph
├── services/               # 비즈니스 로직 레이어
│   ├── collector/          # 수집기
│   ├── preprocessor/       # 전처리기
│   ├── analyzer/           # 분석기
│   ├── embedder/           # 임베더
│   └── auth/               # 인증
├── tasks/                  # 비동기 백그라운드 작업
├── prompts/                # LLM 프롬프트 (YAML)
├── tests/                  # 테스트
└── docs/                   # 문서
```

---

## 레이어 구조

```
HTTP 요청
    ↓
[app/api/routers]       라우터: 요청 수신, 응답 반환
    ↓
[services]              비즈니스 로직 처리
    ↓
[app/db / app/llm]      데이터베이스 or LLM 호출
```

각 레이어는 단방향으로만 의존합니다. 라우터는 services를 호출하고, services는 db/llm을 호출합니다. 역방향 의존은 없습니다.

---

## 디렉토리별 역할

### `app/`

FastAPI 애플리케이션의 핵심 모듈입니다.

```
app/
├── main.py             # FastAPI 앱 생성, 미들웨어, 라우터 등록
├── config.py           # 환경 변수 로딩 (pydantic-settings)
├── api/
│   ├── schemas/        # Pydantic 요청/응답 스키마 (도메인별 파일 + common.py)
│   └── routers/
│       ├── auth.py     # POST /auth/login, /logout, /refresh
│       ├── users.py    # GET/PUT /users/me
│       ├── news.py     # GET /news/today, /news/interests, /news/{id}
│       └── interests.py # GET/POST/DELETE /interests
├── core/
│   ├── security.py     # JWT 생성/검증, 비밀번호 해싱
│   └── errors.py       # 커스텀 예외 클래스
├── db/
│   ├── database.py     # SQLAlchemy 엔진, 세션, Base
│   ├── models.py       # ORM 모델 (User, News, UserInterest)
│   └── queries.py      # DB 쿼리 함수
└── llm/
    ├── prompt_loader.py # prompts/*.yaml 로드 및 캐싱
    ├── state.py         # LangGraph 노드 간 공유 상태 (NewsAnalysisState)
    ├── chains.py        # 개별 LangChain 체인 (필터, 엔티티, 영향도, 해설)
    └── graph.py         # LangGraph 워크플로우 (노드 연결)
```

**`app/api/schemas/`** — Pydantic 스키마만 담습니다(도메인별 파일 분리). ORM 모델(`app/db/orm_models/`)과 분리되어 있습니다.

**`app/db/queries.py`** — 쿼리 로직을 라우터에서 분리합니다. 라우터는 쿼리 함수를 호출만 합니다.

**`app/llm/`** — LangChain과 LangGraph 기반 LLM 파이프라인입니다. `services/analyzer/`가 이 모듈의 래퍼 역할을 합니다.

**워크플로우:**

```
입력 (뉴스 제목 + 본문)
    ↓
[filter]            중요한 뉴스인지 판단 (is_important, confidence)
    ↓
[extract_entities]  기업, 산업, 키워드 추출
    ↓
[analyze_impact]    시장 영향도 분석 (high / medium / low)
    ↓
[generate_explanation]  주린이 수준의 해설 생성
    ↓
NewsAnalysisState 반환
```

**`state.py`** — 모든 노드가 하나의 `NewsAnalysisState` 인스턴스를 공유합니다. 각 노드는 상태를 읽고 업데이트한 뒤 반환합니다.

**`chains.py`** — 각 체인은 `BaseLLMChain`을 상속합니다. `prompt_loader`를 통해 YAML 프롬프트를 로드하고, Vertex AI Gemini를 호출합니다.

---

### `services/`

비즈니스 로직을 담당합니다. 라우터와 LLM/DB 레이어 사이의 중간 계층입니다.
폴더명은 **행위자 명사(-er/-or)** 로 통일합니다. ([컨벤션 규칙 참고](conventions.md))

```
services/
├── collector/                  # 수집기
│   ├── rss_collector.py        # RSSCollector — 연합뉴스, 한국경제 RSS
│   ├── naver_collector.py      # NaverNewsCollector — 네이버 뉴스 검색 API
│   └── finnhub_collector.py    # FinnhubCollector — Finnhub API
├── preprocessor/               # 전처리기
│   ├── deduplicator.py         # NewsDeduplicator — URL/유사도 중복 제거
│   └── filter.py               # NewsFilter — 날짜/LLM 필터링
├── analyzer/                   # 분석기
│   └── gemini_analyzer.py      # GeminiAnalyzer — app/llm/graph.py 래퍼
├── embedder/                   # 임베더
│   └── news_embedder.py        # NewsEmbedder, NewsClustering
└── auth/                       # 인증
    ├── kakao_oauth.py          # KakaoOAuthHandler
    └── google_oauth.py         # GoogleOAuthHandler
```

---

### `tasks/`

주기적으로 실행되는 백그라운드 작업입니다.

```
tasks/
├── collect_news.py         # 뉴스 수집 (RSS + API)
└── generate_analysis.py    # LLM 해설 생성, 임베딩 업데이트
```

라우터의 요청-응답 사이클 밖에서 실행됩니다. APScheduler 또는 Celery와 연동 예정입니다.

---

### `prompts/`

LLM 프롬프트를 YAML로 관리합니다. 코드 변경 없이 프롬프트를 수정할 수 있습니다.

```
prompts/
├── filter.yaml             # 주식 관련 뉴스 필터링 기준
├── entity_extraction.yaml  # 기업, 산업, 키워드 추출
├── impact_analysis.yaml    # 시장 영향도 분석
└── news_explanation.yaml   # 주린이 수준 뉴스 해설
```

**YAML 구조:**

```yaml
name: "prompt_name"
version: "1.0.0"
model: "gemini-1.5-flash"
temperature: 0.7
max_tokens: 1000
template: |
  프롬프트 내용 ({variable})
parameters:
  - name: "variable"
    type: "string"
```

`app/llm/prompt_loader.py`가 런타임에 파일을 읽고 캐싱합니다.
