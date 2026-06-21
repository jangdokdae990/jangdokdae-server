# 장독대 코드 컨벤션

> **작성자** Kim minkyoung · **작성일** 2026-05-27

## 1. 폴더명 규칙

### 기본 원칙

폴더명은 **역할 중심의 행위자 명사(-er/-or)** 로 짓는다.
폴더가 역할을 설명하고, 파일이 구체적인 대상을 설명하는 구조다.

### services/ 하위 폴더

| 폴더 | 의미 | 포함 내용 |
|------|------|-----------|
| `collector/` | 수집기 | RSS, 네이버, Finnhub 수집 |
| `preprocessor/` | 전처리기 | 중복 제거, 필터링 |
| `analyzer/` | 분석기 | LLM 기반 뉴스 분석 |
| `embedder/` | 임베더 | 벡터 임베딩, 클러스터링 |
| `auth/` | 인증 | OAuth, JWT (관용 표현 유지) |

```
# 올바른 예
services/collector/
services/preprocessor/
services/analyzer/

# 잘못된 예 — 동사 원형, 추상 명사 혼용
services/collect/
services/processing/
services/analysis/
```

### app/ 하위 폴더

app/ 내부는 FastAPI 계층을 기준으로 **도메인 명사**를 사용한다.

| 폴더 | 의미 |
|------|------|
| `api/` | HTTP 인터페이스 (라우터, 스키마) |
| `core/` | 공통 기능 (인증, 에러) |
| `db/` | 데이터베이스 |
| `llm/` | LangChain / LangGraph |

### 루트 `utils/` 폴더

앱·서비스 전반에서 쓰는 **무상태 순수 헬퍼**(날짜 변환 등)는 프로젝트 루트 `utils/`에 둔다.
도메인·외부 의존성이 없는 범용 함수만 포함한다. (예: `utils/dates.py`의 `to_naive_kst`)

---

## 2. 파일명 규칙

### 기본 원칙

파일명은 **폴더명(역할) + 구체적인 대상(소스/도메인)** 조합으로 짓는다.
파일명만 봐도 어떤 클래스가 들어있는지 알 수 있어야 한다.

### services/ 하위 파일

폴더명이 역할을 담당하므로 파일명은 **구체적인 소스/대상** 만 표현한다.
단, 폴더명만으로 역할이 충분히 전달되지 않는 경우 `{대상}_{역할}.py` 형태를 사용한다.

```
# collector/ — {소스}_collector.py
collector/rss_collector.py       # RSSCollector
collector/naver_collector.py     # NaverNewsCollector
collector/finnhub_collector.py   # FinnhubCollector

# preprocessor/ — 기능명 그대로 (폴더가 역할 설명)
preprocessor/deduplicator.py     # NewsDeduplicator
preprocessor/filter.py           # NewsFilter

# analyzer/ — {모델명}_analyzer.py
analyzer/gemini_analyzer.py      # GeminiAnalyzer

# embedder/ — {도메인}_embedder.py
embedder/news_embedder.py        # NewsEmbedder, NewsClustering

# auth/ — 클래스가 다르면 파일도 분리, {제공자}_oauth.py
auth/kakao_oauth.py              # KakaoOAuthHandler
auth/google_oauth.py             # GoogleOAuthHandler
```

### app/ 하위 파일

FastAPI 관행에 따라 역할 중심 이름을 사용한다.

```
app/api/schemas/auth.py  # 도메인별 Pydantic 요청/응답 스키마 (auth, onboarding, user …)
app/api/schemas/common.py # 스키마 공통 베이스(ORMSchema)·에러 응답 봉투
app/api/routers/news.py  # 도메인별 라우터 — 도메인명 단수
app/db/orm_models/       # ORM 모델 (모델별 파일 분리: news.py, stock_price.py, common.py)
app/db/queries.py        # 쿼리 함수 모음
app/db/base.py           # Base + 비동기 엔진·세션 + ORM 공통 정의(KST_NOW)
app/core/security.py     # JWT, 비밀번호 처리
app/core/errors.py       # 커스텀 예외
app/llm/chains.py        # LangChain 체인 모음
app/llm/graph.py         # LangGraph 워크플로우
app/llm/state.py         # Graph 상태 정의
app/llm/prompt_loader.py # 프롬프트 로더
```

### 판단 기준 요약

| 상황 | 파일명 형태 | 예시 |
|------|-------------|------|
| 폴더명이 역할을 설명 | 소스/대상만 표현 | `collector/rss.py`, `analyzer/news.py` |
| 파일에 주 클래스 1개, 폴더가 역할 불명확 | `{대상}_{역할}.py` | `news_embedder.py` |
| 여러 클래스가 같은 역할 | `{공통역할}.py` | `chains.py`, `queries.py` |

---

## 3. 클래스명 규칙

**PascalCase**, `{대상}{역할}` 순서로 짓는다.

```python
# 올바른 예
class RSSCollector: ...         # 대상(RSS) + 역할(Collector)
class NaverNewsCollector: ...   # 대상(NaverNews) + 역할(Collector)
class GeminiAnalyzer: ...       # 대상(Gemini) + 역할(Analyzer)
class NewsDeduplicator: ...     # 대상(News) + 역할(Deduplicator)
class KakaoOAuthHandler: ...    # 대상(Kakao) + 역할(OAuthHandler)

# 잘못된 예
class CollectorRSS: ...         # 역할이 앞에 오면 안 됨
class Analyzer: ...             # 대상 없이 역할만 — 너무 추상적
class NewsCollectService: ...   # Service 접미사 불필요 (폴더가 이미 역할을 설명)
```

---

## 4. 함수명 규칙

**snake_case**, `{동사}_{목적어}` 순서로 짓는다.

```python
# 올바른 예
def collect() -> list[dict]: ...
def search_by_symbol(symbol: str) -> list[dict]: ...
def remove_by_url(news_list: list[dict]) -> list[dict]: ...
def filter_by_date(news_list: list[dict], days: int) -> list[dict]: ...
def generate_explanation(news_title: str, news_content: str) -> str: ...
def get_user_by_email(db: Session, email: str): ...

# 잘못된 예
def doCollect(): ...            # camelCase 금지
def news_search(symbol): ...    # 목적어가 앞에 오면 안 됨
def process(): ...              # 너무 추상적
```

### 접두사 컨벤션

| 접두사 | 용도 | 예시 |
|--------|------|------|
| `get_` | 단건 조회 | `get_user_by_email` |
| `get_all_` | 목록 조회 | `get_all_news` |
| `create_` | 생성 | `create_user` |
| `update_` | 수정 | `update_user` |
| `delete_` | 삭제 | `delete_interest` |
| `search_` | 검색 | `search_by_symbol` |
| `filter_` | 필터링 | `filter_by_date` |
| `remove_` | 제거 (삭제가 아닌 가공) | `remove_by_url` |
| `generate_` | LLM 생성 | `generate_explanation` |
| `analyze_` | 분석 | `analyze_impact` |
| `embed_` | 임베딩 | `embed_news` |

---

## 5. 변수명 규칙

**snake_case**, 타입을 유추할 수 있는 이름을 사용한다.

```python
# 올바른 예
news_list: list[dict]
user_id: int
access_token: str
is_important: bool
impact_level: str

# 잘못된 예
data = []        # 너무 추상적
l = []           # 단일 문자
newsData = []    # camelCase 금지
```

### 불리언 변수

`is_`, `has_`, `can_` 접두사를 붙인다.

```python
is_important: bool
has_explanation: bool
can_retry: bool
```

### 컬렉션 변수

복수형을 사용한다.

```python
news_list: list[dict]    # list
companies: list[str]     # list (복수형)
unique_urls: set[str]    # set
```

---

## 6. 주석 규칙

### 기본 원칙

**WHY(왜)를 설명**한다. WHAT(무엇)은 코드가 이미 설명한다.

```python
# 올바른 예 — 이유를 설명
# URL 기반 1차 제거 후 유사도 검사 → 순서가 바뀌면 LLM 비용 증가
deduped = self.remove_by_url(news_list)
deduped = self.remove_by_similarity(deduped)

# 잘못된 예 — 코드를 그대로 반복
# URL로 중복 제거
deduped = self.remove_by_url(news_list)
```

### TODO 주석

미구현 부분은 `# TODO:` 형식으로 작성한다.

```python
# TODO: Finnhub API 호출 구현
return []
```

### 모듈 docstring

파일 상단에 모듈 역할을 한 줄로 작성한다.

```python
"""RSS 피드 뉴스 수집기"""
```

### 클래스/함수 docstring

외부에 노출되는 public 메서드에만 작성한다. 내부 구현이 복잡하거나, 파라미터 의미가 불명확할 때만 추가한다.

```python
# 필요한 경우
def analyze_news(self, news_title: str, news_content: str) -> NewsAnalysisState:
    """뉴스 전체 분석 (필터링 → 엔티티 추출 → 영향도 분석 → 해설 생성)"""

# 불필요한 경우 — 함수명이 이미 충분히 설명
def get_user_by_email(db: Session, email: str):
    return db.query(User).filter(User.email == email).first()
```

---

## 7. 커밋 메시지 규칙

`{타입}: {변경 내용}` 형식을 사용한다.

| 타입 | 용도 |
|------|------|
| `feat` | 새 기능 추가 |
| `fix` | 버그 수정 |
| `refactor` | 기능 변화 없는 코드 개선 |
| `docs` | 문서 추가/수정 |
| `test` | 테스트 추가/수정 |
| `chore` | 빌드, 설정, 의존성 변경 |

```bash
# 올바른 예
feat: 네이버 뉴스 검색 API 수집기 추가
fix: RSS 피드 중복 수집 버그 수정
refactor: services/ 폴더 기능별 분리
docs: 코드 컨벤션 문서 작성
chore: alembic 의존성 추가

# 잘못된 예
update code           # 타입 없음
feat: 기능 추가       # 내용이 구체적이지 않음
```

---

## 8. import 순서 규칙

ruff / isort 기준을 따른다. 그룹 사이에 빈 줄 하나를 넣는다.

```python
# 1. 표준 라이브러리
import json
import logging

# 2. 서드파티
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

# 3. 내부 모듈 (app → services 순)
from app.config import settings
from app.db.database import get_db
from services.analyzer.news import GeminiAnalyzer
```

---

## 9. 타입 힌트 규칙

모든 함수의 파라미터와 반환값에 타입 힌트를 작성한다.

```python
# 올바른 예
def remove_by_url(self, news_list: list[dict]) -> list[dict]:
def get_user_by_email(db: Session, email: str) -> User | None:
def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:

# 잘못된 예
def remove_by_url(self, news_list):
def get_user_by_email(db, email):
```

Python 3.12 이상이므로 `Optional[str]` 대신 `str | None`을 사용한다.

```python
# 권장
def analyze_news(self, news_url: str | None = None) -> NewsAnalysisState:

# 비권장 (구버전 스타일)
def analyze_news(self, news_url: Optional[str] = None) -> NewsAnalysisState:
```
