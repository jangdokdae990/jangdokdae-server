# 에이전트 오케스트레이션 아키텍처

**작성일** 2026-05-28  
**기획 범위** 수집 → 전처리 → 임베딩·클러스터링 전체 파이프라인  
**관련 문서**  
- [뉴스 데이터 수집 기획서](./02-news-collection-design.md)
- [기업 데이터 수집 기획서](./03-company-data-collection-design.md)
- [전처리 기획서](./04-preprocessing-design.md)
- [임베딩·클러스터링 기획서](./05-embedding-clustering-design.md)

---

## 목차

- [1. 왜 에이전트 구조인가](#1-왜-에이전트-구조인가)
- [2. 전체 구조](#2-전체-구조)
- [3. MasterOrchestrator](#3-masterorchestrator)
- [4. NewsCollectionAgent](#4-newscollectionagent)
- [5. CompanyCollectionAgent](#5-companycollectionagent)
- [6. PreprocessingAgent](#6-preprocessingagent)
- [7. EmbeddingClusteringAgent](#7-embeddingclusteringagent)
- [8. 공유 도구 (Tools)](#8-공유-도구-tools)
- [9. DB 스키마 요구사항](#9-db-스키마-요구사항)
- [10. 에러 처리 전략](#10-에러-처리-전략)
- [11. 디렉토리 구조](#11-디렉토리-구조)
- [12. 구현 순서](#12-구현-순서)

---

## 1. 왜 에이전트 구조인가

단순 수집 방식의 한계:

| 문제 | 설명 |
|------|------|
| 예상 밖 이슈 대응 불가 | 고정 키워드로는 갑작스러운 시장 이슈를 놓침 |
| 수집 품질 무감각 | 100건 수집 후 2건만 분석 통과해도 감지 못함 |
| "오늘 중요한 뉴스" 선정 주체 없음 | 단순 수집은 기사 목록만 만들 뿐, 우선순위 없음 |
| 수집·전처리·임베딩이 각자 독립 | 하나가 실패해도 다른 단계가 모름 |

에이전트 구조는 이를 해결한다.

- **NewsCollectionAgent**: 수집 중 스스로 "충분한가" 판단 → 부족하면 추가 검색
- **MasterOrchestrator**: 4개 에이전트의 실행 순서·의존성·에러를 한 곳에서 관리

---

## 2. 전체 구조

```
Airflow (dags/)
      │
      ▼
MasterOrchestrator
      │
      ├── NewsCollectionAgent ─────────────────┐
      │   (LangGraph)                          │
      │                                        │ 공유 DB
      ├── CompanyCollectionAgent ──────────────┤ (PostgreSQL)
      │   (LangGraph)                          │
      │                                        │
      ├── PreprocessingAgent ──────────────────┤
      │   (순차 실행)                           │
      │                                        │
      └── EmbeddingClusteringAgent ────────────┘
          (순차 실행)
                │
                ▼
          분석 파이프라인 트리거
          (app/llm/graph.py — 타인 담당)
```

**핵심 원칙**: 에이전트끼리 직접 호출하지 않는다. **공유 DB를 통해서만 데이터를 전달**한다.

---

## 3. MasterOrchestrator

### 3.1 역할

**스케줄링·의존성·실패 처리는 Airflow DAG(Direted Acyclic Graph)가 담당**한다.  
`MasterOrchestrator`는 각 에이전트를 호출하는 Python 헬퍼로 축소된다.

- 에이전트 실행 순서 캡슐화 (Airflow Task에서 호출)
- 에이전트 간 에러 격리 (`return_exceptions=True`)

스케줄링·재시도·이력 관리는 Airflow가 처리하므로 `MasterOrchestrator`가 직접 스케줄을 들고 있지 않아도 된다.

### 3.2 Airflow DAG 구성

파이프라인 타이밍별로 DAG를 분리한다.

| DAG | cron (KST) | Task 구성 |
|-----|-----------|----------|
| `jangdokdae_morning` | `0 9 * * 1-5` (평일 09:00) | collect_news ∥ collect_company → preprocess → embed |
| `jangdokdae_afternoon` | `30 15 * * 1-5` (평일 15:30) | collect_news ∥ collect_company → preprocess → embed → trigger_analysis |
| `jangdokdae_market_close` | `30 16 * * 1-5` (평일 16:30) | collect_market_data |
| `jangdokdae_quarterly` | `0 9 1 1,4,7,10 *` (분기 첫날) | collect_reports → embed |

### 3.3 Airflow DAG 구현

```python
# dags/jangdokdae_morning.py
import asyncio
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
from services.master_orchestrator import MasterOrchestrator

orchestrator = MasterOrchestrator()

def collect_news_task(**ctx):
    asyncio.run(orchestrator.news_agent.run("morning"))

def collect_company_task(**ctx):
    asyncio.run(orchestrator.company_agent.run("morning"))

def preprocess_task(**ctx):
    asyncio.run(orchestrator.preprocessing.run())

def embed_task(**ctx):
    asyncio.run(orchestrator.embedding.run())

with DAG(
    dag_id="jangdokdae_morning",
    schedule_interval="0 9 * * 1-5",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": 60},
) as dag:

    t_news    = PythonOperator(task_id="collect_news",    python_callable=collect_news_task)
    t_company = PythonOperator(task_id="collect_company", python_callable=collect_company_task)
    t_prep    = PythonOperator(task_id="preprocess",      python_callable=preprocess_task)
    t_embed   = PythonOperator(task_id="embed_cluster",   python_callable=embed_task)

    # 수집은 병렬, 이후 순차
    [t_news, t_company] >> t_prep >> t_embed
```

### 3.4 MasterOrchestrator (Airflow 호환)

```python
# services/master_orchestrator.py
import asyncio
import logging
from services.agents.news_collection_agent import NewsCollectionAgent
from services.agents.company_collection_agent import CompanyCollectionAgent
from services.agents.preprocessing_agent import PreprocessingAgent
from services.agents.embedding_clustering_agent import EmbeddingClusteringAgent

logger = logging.getLogger(__name__)


class MasterOrchestrator:
    """에이전트 호출 헬퍼. 스케줄링은 Airflow DAG가 담당."""

    def __init__(self):
        self.news_agent    = NewsCollectionAgent()
        self.company_agent = CompanyCollectionAgent()
        self.preprocessing = PreprocessingAgent()
        self.embedding     = EmbeddingClusteringAgent()

    async def run_collection(self, schedule: str) -> None:
        results = await asyncio.gather(
            self.news_agent.run(schedule),
            self.company_agent.run(schedule),
            return_exceptions=True,
        )
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[{['NewsAgent','CompanyAgent'][i]}] 실패: {result}")

    async def run_postprocess(self) -> None:
        await self.preprocessing.run()
        await self.embedding.run()

    async def trigger_analysis_pipeline(self) -> None:
        """is_analyzed=False 레코드를 분석 파이프라인에 넘김 (타인 담당)"""
        pass
```

### 3.5 Airflow 장점

| 항목 | APScheduler | **Airflow** |
|------|------------|------------|
| 실행 이력 UI | ❌ | ✅ Web UI (성공/실패/소요 시간) |
| 재시도 정책 | 수동 구현 | ✅ `retries`, `retry_delay` 선언적 |
| 태스크 병렬성 | 직접 코딩 | ✅ DAG 의존성으로 자동 처리 |
| 분산 실행 | ❌ | ✅ CeleryExecutor로 스케일아웃 |
| 실패 알림 | 없음 | ✅ Email/Slack 알림 내장 |
| 서버 재시작 후 | 스케줄 유실 | ✅ DB 기반으로 유지 |

---

## 4. NewsCollectionAgent

뉴스 수집의 **수집 + 클러스터링 + 중요도 판단 + DB 저장**을 담당한다.  
상세 내용은 [`02-news-collection-design.md`](./02-news-collection-design.md) 참조.

### 4.1 상태 (State)

```python
class NewsAgentState(TypedDict):
    schedule: str                  # "morning" | "afternoon"
    keywords: list[str]            # 수집할 키워드 목록
    collected: list[dict]          # 수집된 원시 뉴스
    clusters: list[dict]           # 클러스터 목록 (이슈 단위)
    scored: list[dict]             # 볼륨·속도 점수 붙은 클러스터
    top_issues: list[dict]         # 최종 선정 이슈
    needs_expansion: bool          # 추가 검색 필요 여부
    expansion_count: int           # 루프 횟수 (최대 2회)
    errors: list[str]
```

### 4.2 노드 구성

```
[collect] → [cluster] → [evaluate] → [finalize]
                              ↑            ↓
                         [expand] ←────────┘ (needs_expansion=True, max 2회)
```

| 노드 | 역할 | 사용 도구 |
|------|------|---------|
| `collect` | 키워드 기반 뉴스 수집, 정규화, URL 중복 제거 | `search_tool`, `save_tool` |
| `cluster` | 유사 뉴스 클러스터링 + 볼륨·속도 스코어 계산 | `cluster_tool`, `score_tool` |
| `evaluate` | LLM: 충분한 이슈가 수집됐는가? 추가 키워드 제안 | Vertex AI Gemini |
| `expand` | 추가 키워드로 재수집 → cluster 노드 복귀 | `expand_tool` |
| `finalize` | 상위 이슈 선정, DB 저장, embedding=NULL 마킹 | `save_tool` |

### 4.3 루프 제한

```python
# evaluate_node
if state["expansion_count"] >= 2:
    return {"needs_expansion": False}

# graph 호출 시 하드 상한
graph.invoke(initial_state, config={"recursion_limit": 10})
```

---

## 5. CompanyCollectionAgent

기업 데이터(공시·주가·환율·거시지표·재무제표) 수집을 담당한다.  
상세 내용은 [`03-company-data-collection-design.md`](./03-company-data-collection-design.md) 참조.

### 5.1 상태 (State)

```python
class CompanyAgentState(TypedDict):
    schedule: str           # "morning" | "afternoon" | "market_close" | "quarterly"
    target_symbols: list[str]
    collected_disclosures: int
    collected_prices: int
    collected_indicators: int
    errors: list[str]
```

### 5.2 노드 구성

`schedule` 파라미터로 실행 경로를 분기한다.

```
[route]
  ├─ morning / afternoon  →  [dart_collect]
  ├─ market_close         →  [market_collect]  (주가 + 환율 병렬)
  └─ quarterly            →  [financial_collect]  (사업보고서 + 재무제표)
        │
        ▼
   [finalize]  →  DB 저장
```

---

## 6. PreprocessingAgent

수집 완료 후 DB에서 `preprocessed_at IS NULL` 레코드를 읽어 정규화·필터링한다.  
상세 설계는 [`04-preprocessing-design.md`](./04-preprocessing-design.md) 참조.

### 6.1 처리 순서

```
DB (preprocessed_at IS NULL 레코드 조회)
    │
    ├── 1. HTML 정제 (Naver <b> 태그 제거)
    ├── 2. 타임존 정규화 (published_at → UTC)
    ├── 3. URL 정규화 (Google RSS 리다이렉트 → 실제 URL, 트래킹 파라미터 제거)
    ├── 4. 날짜·snippet 필터 (24시간 초과 / 20자 미만 → 삭제)
    └── 5. preprocessed_at = now() 업데이트
```

### 6.2 상태 (State)

```python
class PreprocessingAgentState(TypedDict):
    batch_size: int
    processed: int
    filtered_out: int
    errors: list[str]
```

---

## 7. EmbeddingClusteringAgent

전처리 완료 레코드에 임베딩을 생성하고 pgvector에 저장한다.  
상세 설계는 [`05-embedding-clustering-design.md`](./05-embedding-clustering-design.md) 참조.

### 7.1 처리 순서

```
DB (embedding=NULL 레코드 조회)
    │
    ├── 1. 제목 + snippet 텍스트 결합
    ├── 2. Vertex AI text-multilingual-embedding-002 호출
    ├── 3. News.embedding 컬럼 업데이트
    └── 4. 벡터 유사도 기반 최종 중복 제거 (cosine ≥ 0.95)
```

### 7.2 임베딩 모델

| 항목 | 내용 |
|------|------|
| 모델 | `text-multilingual-embedding-002` |
| 차원 | 768 |
| 선정 이유 | 한국어 포함 다국어 지원, Vertex AI 기존 인프라 재사용 |
| 환경 변수 | `EMBEDDING_MODEL=text-multilingual-embedding-002` |

---

## 8. 공유 도구 (Tools)

에이전트가 공통으로 사용하는 도구. `services/collector/tools/`에 위치한다.

| 도구 | 경로 | 사용 에이전트 |
|------|------|-------------|
| `search_tool` | `tools/search_tool.py` | NewsCollectionAgent |
| `cluster_tool` | `tools/cluster_tool.py` | NewsCollectionAgent |
| `score_tool` | `tools/score_tool.py` | NewsCollectionAgent |
| `expand_tool` | `tools/expand_tool.py` | NewsCollectionAgent |
| `dart_tool` | `tools/dart_tool.py` | CompanyCollectionAgent |
| `stock_tool` | `tools/stock_tool.py` | CompanyCollectionAgent |
| `macro_tool` | `tools/macro_tool.py` | CompanyCollectionAgent |
| `save_tool` | `tools/save_tool.py` | **모든 에이전트 공유** |

### save_tool 인터페이스

모든 에이전트가 동일한 `save_tool`을 통해 DB에 저장한다.

```python
# services/collector/tools/save_tool.py
from sqlalchemy.dialects.postgresql import insert

async def upsert_news(db: AsyncSession, records: list[dict]) -> int:
    stmt = insert(News).values(records)
    stmt = stmt.on_conflict_do_nothing(index_elements=["url"])
    result = await db.execute(stmt)
    await db.commit()
    return result.rowcount
```

---

## 9. DB 스키마 요구사항

에이전트 파이프라인이 동작하기 위해 필요한 DB 필드.

### 에이전트 처리 상태 추적 컬럼

**`news` 테이블** (뉴스 수집 기획서 스키마 기준)

| 컬럼 | 타입 | 용도 |
|------|------|------|
| `title` | String(500) | 뉴스 제목 |
| `snippet` | Text | API 제공 snippet/summary |
| `url` | String(500), unique | 원문 URL — 중복 방지 키 |
| `source` | String(100) | `"google_rss_ko"` \| `"naver"` \| `"google_rss_en"` \| `"finnhub"` |
| `source_type` | String(50) | `"market_news"` \| `"stock_news"` |
| `region` | String(10) | `"domestic"` \| `"global"` |
| `symbol` | String(20), nullable | 종목 코드 (종목 뉴스만) |
| `is_analyzed` | Boolean | 분석 파이프라인 처리 여부 |
| `published_at` | DateTime(timezone=True) | 기사 발행 시각 (UTC) |
| `embedding` | Vector(768), nullable | EmbeddingClusteringAgent 저장 |
| `original_url` | String(500), nullable | Google RSS 리다이렉트 원본 URL 보존 |

**`disclosures` 테이블** (기업 데이터 수집 기획서 스키마 기준)

| 컬럼 | 타입 | 용도 |
|------|------|------|
| `rcept_no` | String(20), unique | DART 접수번호 |
| `title` | String(500) | 공시 제목 |
| `content` | Text | 공시 본문 전체 |
| `corp_code` | String(20) | 기업 고유번호 |
| `stock_code` | String(20), nullable | 종목 코드 |
| `disclosure_type` | String(50) | 공시 유형 |
| `is_analyzed` | Boolean | 분석 파이프라인 처리 여부 |
| `disclosed_at` | DateTime(timezone=True) | 공시 일시 (UTC) |
| `embedding` | Vector(768), nullable | RAG 검색용 |

**`report_chunks` 테이블**

| 컬럼 | 타입 | 용도 |
|------|------|------|
| `corp_code` | String(20) | 기업 고유번호 |
| `report_year` | Integer | 보고서 연도 |
| `chunk_type` | String(50) | `"business_summary"` \| `"risk_factors"` \| `"financial_summary"` |
| `content` | Text | 청크 본문 |
| `embedding` | Vector(768), nullable | RAG 검색용 |

> ¹ 현재 기본값 768. 임베딩 모델 변경 시(BGE-M3 등) `Vector(1024)`로 전체 테이블 동시 변경 필요. `EMBEDDING_DIM` 환경 변수로 관리 권장.

### 마이그레이션 전략

기존 `News` 모델과 기획서 스키마가 다르므로 Alembic으로 단계적 마이그레이션이 필요하다.

```bash
uv add alembic
alembic init alembic
alembic revision --autogenerate -m "add agent pipeline fields"
alembic upgrade head
```

---

## 10. 에러 처리 전략

### 에이전트 수준

```python
# MasterOrchestrator — gather에서 예외 캡처
results = await asyncio.gather(
    self.news_agent.run(schedule),
    self.company_agent.run(schedule),
    return_exceptions=True,
)
```

| 시나리오 | 처리 방식 |
|---------|---------|
| NewsAgent 실패 | 로그 기록 → CompanyAgent는 계속 → 전처리·임베딩은 기존 데이터로 진행 |
| CompanyAgent 실패 | 로그 기록 → NewsAgent 결과는 처리 |
| PreprocessingAgent 실패 | ERROR 알림 → preprocessed_at IS NULL 레코드 다음 주기 재처리 |
| EmbeddingAgent 실패 | ERROR 알림 → `embedding=NULL` 레코드는 다음 주기에 처리 |

### 도구 수준 — 재시도 (exponential backoff)

```python
import asyncio
from functools import wraps

def with_retry(max_attempts: int = 3):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_attempts - 1:
                        raise
                    wait = 2 ** attempt   # 1s → 2s → 4s
                    await asyncio.sleep(wait)
        return wrapper
    return decorator
```

---

## 11. 디렉토리 구조

```
services/
  ├── master_orchestrator.py              ← MasterOrchestrator
  │
  ├── agents/                             ← 에이전트 (LangGraph 그래프)
  │   ├── news_collection_agent.py
  │   ├── company_collection_agent.py
  │   └── embedding_clustering_agent.py
  │
  ├── collector/                          ← 수집기 + 도구
  │   ├── tools/
  │   │   ├── search_tool.py
  │   │   ├── cluster_tool.py
  │   │   ├── score_tool.py
  │   │   ├── expand_tool.py
  │   │   ├── dart_tool.py
  │   │   ├── stock_tool.py
  │   │   ├── macro_tool.py
  │   │   └── save_tool.py
  │   ├── google_news_collector.py
  │   ├── naver_collector.py
  │   ├── finnhub_collector.py
  │   ├── dart_collector.py
  │   ├── stock_collector.py
  │   └── macro_collector.py
  │
  ├── preprocessor/
  │   ├── deduplicator.py
  │   ├── filter.py
  │   └── normalizer.py
  │
  └── embedder/
      ├── news_embedder.py
      └── cluster.py

dags/                              ← Airflow DAG 정의
  ├── jangdokdae_morning.py      ← 09:00 평일 (수집 + 전처리 + 임베딩)
  ├── jangdokdae_afternoon.py    ← 15:30 평일 (수집 + 전처리 + 임베딩 + 분석 트리거)
  ├── jangdokdae_market_close.py ← 16:30 평일 (주가·거시지표만)
  └── jangdokdae_quarterly.py    ← 분기 첫날 (사업보고서 + 임베딩)
```

---

## 12. 구현 순서

에이전트는 **도구 → 에이전트 → 오케스트레이터** 순서로 구현한다.  
각 레이어를 독립적으로 테스트 가능하다.

| 단계 | 내용 | 선행 조건 |
|------|------|---------|
| 1 | Alembic 설정 + DB 마이그레이션 | — |
| 2 | `AsyncSession` + `asyncpg` 전환 | — |
| 3 | 수집기 구현 (google, naver, finnhub, dart, stock, macro) | API 키 발급 |
| 4 | `tools/` 구현 (search, save, dart, stock, macro) | 수집기 완료 |
| 5 | `NewsCollectionAgent` 구현 (collect → cluster → evaluate → finalize) | pgvector 활성화 |
| 6 | `CompanyCollectionAgent` 구현 | — |
| 7 | `PreprocessingAgent` 구현 | `services/agents/preprocessing_agent.py` |
| 8 | `EmbeddingClusteringAgent` 구현 | 임베딩 모델 선정 |
| 9 | Airflow 설치 + DAG 4개 작성 (`dags/`) | 에이전트 4개 완료 |
| 10 | 통합 테스트 (전체 파이프라인 end-to-end) | — |
