# 장독대 - 주린이를 위한 주식 뉴스 큐레이션 & 학습 서비스

## 프로젝트 개요

**목표:** 주식 초보자(주린이)를 위한 주식 뉴스 큐레이션 및 학습 서비스

**핵심 가치:** 어려운 증권 뉴스를 LLM을 통해 초보자가 이해하기 쉽게 풀어서 설명

## 기술 스택

- **백엔드:** Python 3.12, FastAPI
- **데이터베이스:** PostgreSQL (Neon), pgvector
- **인증:** OAuth 2.0 (카카오, 구글)
- **LLM:** Vertex AI (Gemini), LangChain, LangGraph
- **패키지 관리:** uv

## 프로젝트 구조

```
app/
├── main.py              # 앱 진입점
├── config.py            # 설정 관리
├── dependencies.py      # 공통 의존성
├── api/                 # API 엔드포인트
│   ├── models.py       # Pydantic 스키마
│   └── routers/        # 라우터 (auth, users, news)
├── core/               # 핵심 기능
│   ├── security.py     # 인증 & JWT
│   └── errors.py       # 커스텀 예외
└── db/                 # 데이터베이스
    ├── models.py       # SQLAlchemy ORM
    └── queries.py      # DB 쿼리

services/              # 비즈니스 로직
├── news_collection.py  # 뉴스 수집
├── news_processing.py  # 전처리 & 필터링
├── llm_analysis.py     # LLM 분석
└── embedding.py        # 임베딩 & 클러스터링

tasks/                 # 비동기 작업
├── collect_news.py    # 뉴스 수집 작업
└── generate_analysis.py # 분석 생성 작업

tests/                 # 테스트
```

## 설치 및 실행

### 1. 환경 설정

```bash
# Python 3.12 환경 확인
python --version

# uv로 패키지 설치
uv sync

# .env 파일 생성
cp .env.example .env
# .env 파일 수정 (데이터베이스, OAuth, LLM 설정)
```

### 2. 데이터베이스 초기화

```bash
# 마이그레이션 스크립트 (추후 Alembic 추가)
python -m scripts.init_db
```

### 3. 로컬 실행

```bash
# 개발 서버 실행
uvicorn app.main:app --reload

# 또는
python -m app.main
```

앱이 실행되면: http://localhost:8000

API 문서: http://localhost:8000/docs (Swagger)

### 4. 테스트 실행

```bash
# 전체 테스트
pytest

# 커버리지 포함
pytest --cov=app
```

## API 엔드포인트

### 인증 (Auth)
- `POST /api/v1/auth/login` - 로그인
- `POST /api/v1/auth/logout` - 로그아웃
- `POST /api/v1/auth/refresh` - 토큰 갱신

### 사용자 (Users)
- `POST /api/v1/users/register` - 회원가입
- `GET /api/v1/users/me` - 현재 사용자 조회
- `PUT /api/v1/users/me` - 사용자 정보 업데이트

### 뉴스 (News)
- `GET /api/v1/news/today` - 오늘의 주요 뉴스
- `GET /api/v1/news/interests` - 관심 종목 뉴스
- `GET /api/v1/news/{news_id}` - 뉴스 상세 조회

## 파이프라인

뉴스 수집 → 전처리 → 임베딩·클러스터링 → 엔티티 추출 → 분석 → 해설 생성

### 뉴스 수집 (News Collection)

#### 파이프라인 1: 주요 시장 뉴스
- 국내: 연합뉴스, 한국경제 (RSS)
- 국외: Reuters, AP (RSS)

#### 파이프라인 2: 종목/섹터별 뉴스
- 국내 종목: 네이버 뉴스 검색 API
- 국외 종목: Finnhub API

### 전처리
- URL 기반 중복 제거
- 제목 유사도 기반 중복 제거
- LLM 필터링 (영향도 판단)

### LLM 해설
- 단순 요약이 아닌 맥락 있는 해설
- 주린이 눈높이에 맞는 용어 풀이
- 원문 출처 항상 노출

## 환경 변수 설정

`.env` 파일에서 다음을 설정하세요:

```env
DATABASE_URL=postgresql://...
OAUTH_KAKAO_CLIENT_ID=...
OAUTH_KAKAO_CLIENT_SECRET=...
OAUTH_GOOGLE_CLIENT_ID=...
OAUTH_GOOGLE_CLIENT_SECRET=...
SECRET_KEY=...
VERTEX_AI_PROJECT_ID=...
```

## 개발 가이드

### 코드 스타일
- Black, Ruff, MyType 사용
- 각 모듈은 단일 책임 원칙 준수

### 커밋 컨벤션
```
feat: 새 기능
fix: 버그 수정
refactor: 리팩토링
docs: 문서화
test: 테스트 추가
chore: 빌드, 설정 변경
```

### 테스트
- 주요 로직은 유닛 테스트 작성
- 비동기 함수는 `pytest-asyncio` 사용

## 라이선스

MIT

## 문의

alsrud9259@gmail.com
