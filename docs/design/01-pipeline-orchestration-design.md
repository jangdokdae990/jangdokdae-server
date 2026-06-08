# 파이프라인 오케스트레이션 (L1 정형 단계 — 통합 개요)

> **작성자** Kim minkyoung · **작성일** 2026-05-28 (2026-06-08 통합 개요로 슬림화)
>
> **범위** L1 정형 파이프라인의 통합 개요 — 데이터 흐름·단계 인덱스·공유 도구·DB 스키마 맵·빌드 순서
>
> **관련 문서**
>
> - [Airflow 워크플로우 오케스트레이션](./00-workflow-airflow.md) — L1 실행 골격(스케줄·DAG)과 L1/L2 배치 기준, 2계층 모델
> - [뉴스 분석 설계 (L2 AI 에이전트 오케스트레이션)](./06-news-analysis-design.md#18-newsanalysisagent-설계) — 분석→Issue Docent
> - [뉴스 데이터 수집 기획서](./02-news-collection-design.md)
> - [기업 데이터 수집 기획서](./03-company-data-collection-design.md)
> - [전처리 기획서](./04-preprocessing-design.md)
> - [임베딩·클러스터링 기획서](./05-embedding-clustering-design.md)

---

이 문서는 [2계층 오케스트레이션 모델](./00-workflow-airflow.md#2계층-오케스트레이션-모델)의 **L1 — 정형 파이프라인**의 **통합 개요**다. 전체 데이터 흐름, 단계 인덱스, 공유 도구, DB 스키마 맵, 빌드 순서를 한곳에 모은다.

> 각 단계의 State·노드·알고리즘 **상세는 02~05를 단일 출처**로 한다. 본 문서는 그 단계들을 **잇는 관점**(데이터 흐름·공통 계약·실행 순서)만 다루며, 단계 내부를 중복 기술하지 않는다. 실행 골격(스케줄·DAG·러너)은 [00](./00-workflow-airflow.md), 분석(L2)은 [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계).

## 목차

- [1. 왜 이 구조인가](#1-왜-이-구조인가)
- [2. 전체 구조 & 데이터 핸드오프](#2-전체-구조--데이터-핸드오프)
- [3. 파이프라인 단계 인덱스](#3-파이프라인-단계-인덱스)
- [4. 공유 도구 (Tools)](#4-공유-도구-tools)
- [5. DB 스키마 맵](#5-db-스키마-맵)
- [6. 에러 처리](#6-에러-처리)
- [7. 디렉토리 구조](#7-디렉토리-구조)
- [8. 통합 빌드 순서](#8-통합-빌드-순서)

---

## 1. 왜 이 구조인가

단순 수집 방식의 한계:

| 문제 | 설명 |
|------|------|
| "오늘 중요한 뉴스" 선정 주체 없음 | 단순 수집은 기사 목록만 만들 뿐, 우선순위 없음 |
| 수집·전처리·임베딩이 각자 독립 | 하나가 실패해도 다른 단계가 모름 |

구조화된 파이프라인은 이를 해결한다.

- **스코어링·클러스터링**: 임베딩·클러스터링 단계(EmbeddingClusterer)가 `cluster_tool`·`score_tool`로 클러스터를 복합 중요도로 평가해 "오늘 중요한 이슈"를 선정하고 `news_cluster`에 적재한다(→ [05](./05-embedding-clustering-design.md)). 수집 단계는 수집·저장만 한다.
- **Airflow 파이프라인**: 수집·전처리·임베딩을 한 DAG에서 관리해 실행 순서·단계 간 실패를 격리한다. 스케줄·의존성·재시도 모두 Airflow가 담당한다(별도 오케스트레이터 객체 없음) → [00](./00-workflow-airflow.md).
- **LangGraph는 추론이 필요한 단계에 한정**: 분석 → Issue Docent만 LLM 추론·분기가 필요해 LangGraph 에이전트로 둔다(→ [06](./06-news-analysis-design.md)). 수집·전처리·임베딩·클러스터링은 흐름이 정형이라 Airflow Task로 실행된다.

> 각 단계를 L1(Airflow)/L2(LangGraph) 중 어디에 둘지의 **판단 기준과 7단계 배치 매핑**은 [00의 기획 부](./00-workflow-airflow.md#2-경계-기준--흐름-제어flow-control)에 있다.

---

## 2. 전체 구조 & 데이터 핸드오프

```
Airflow DAG (각 Task가 단계를 직접 호출 → 00)
      │
      ├── NewsCollector (수집→전처리→저장) ┐
      ├── CompanyCollector     (정적 분기)  │  공유 DB
      └── EmbeddingClusterer                ┘ (PostgreSQL)
                │
                ▼
          analyze (L2 에이전트 → 06 §18) → Issue Docent
```

**핵심 원칙**: 단계끼리 직접 호출하지 않는다. **공유 DB의 상태 컬럼을 통해 데이터를 전달**한다(상태 핸드오프). 외부 호출에 의존해 독립 실패·재시도가 필요한 단계(임베딩·분석)만 DB 핸드오프로 잇고, 순수 인메모리인 뉴스 전처리는 수집 노드 안에 합쳐 정제본을 1회 저장한다(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)). 각 단계는 "미처리 레코드"만 집어가므로 느슨하게 결합되고, 부분 실패 후 재실행해도 남은 것만 처리된다(멱등).

| 단계 | 읽는 조건 | 끝나면 |
|------|----------|--------|
| NewsCollector(수집+전처리) / CompanyCollector | — | INSERT 정제본 (`is_filtered`, `embedding=NULL`, `is_analyzed=false`) |
| EmbeddingClusterer | `is_filtered = FALSE AND embedding IS NULL` | `embedding` 채움 + `news_cluster` 적재(`importance`) |
| NewsAnalysisAgent (L2) | `is_analyzed=false` | Issue Docent 생성, `is_analyzed=true` |

> 이 상태 컬럼들이 단계 간 **계약**이다. 실행 순서(병렬·의존성)와 재시도·재개는 [00 §6~§7](./00-workflow-airflow.md#6-전체-구조)을 참조한다.

---

## 3. 파이프라인 단계 인덱스

각 단계의 State·노드·알고리즘 상세는 **해당 문서를 단일 출처**로 한다(여기서는 중복 기술하지 않는다).

| # | 단계 (클래스) | 역할 | 배치 | 상세 |
|---|------|------|------|:---:|
| 1 | **NewsCollector** | 뉴스 수집 → **전처리(인메모리)** → 저장 (`collect→preprocess→save`) | Airflow Task (정적 순차) | [02](./02-news-collection-design.md#7-뉴스-수집-단계) · [04](./04-preprocessing-design.md) |
| 2 | **CompanyCollector** | 공시·주가·환율·거시·재무 수집 (`schedule` 분기) | Airflow Task (정적 분기) | [03](./03-company-data-collection-design.md#7-수집-파이프라인-아키텍처) |
| 3 | **EmbeddingClusterer** | 임베딩 → 벡터 중복 제거 → 클러스터링 → 이슈 선정 | Airflow Task | [05](./05-embedding-clustering-design.md#8-embeddingclusterer-설계) |
| 4 | **NewsAnalysisAgent** | 분류 → 콘텐츠 생성 → Issue Docent (L2 추론) | LangGraph 슈퍼바이저-워커 | [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계) |

> 뉴스 전처리(HTML·URL 정규화 + 날짜 필터 + 제목 중복)는 별도 Task가 아니라 **NewsCollector 안의 인메모리 모듈**(`news_preprocessor.run_preprocessing`)이다 — 외부 의존성이 없어 DB 핸드오프가 불필요하기 때문(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)). 1~3은 **L1 정형 단계**, 4는 **L2 에이전트**(별도 담당)다.

---

## 4. 공유 도구 (Tools)

단계가 공통으로 사용하는 도구. `services/collector/tools/`에 위치한다.

| 도구 | 경로 | 사용 단계 |
|------|------|-------------|
| `save_tool` | `tools/save_tool.py` | **모든 단계 공유** (테이블별 UPSERT 경계) |
| `company_loader` | `tools/company_loader.py` | CompanyCollector (is_active 기업 로드) |
| `redact` | `tools/redact.py` | 수집기 공통 (로그 API 키 마스킹) |
| `cluster_tool` | `tools/cluster_tool.py` | EmbeddingClusterer (클러스터링) |
| `score_tool` | `tools/score_tool.py` | EmbeddingClusterer (복합 중요도 스코어) |

> **수집기는 도구가 아니다**: 뉴스·기업 수집의 개별 수집기(`rss_collector`·`dart_collector`·`financial_collector`·`report_collector`·`stock_collector`·`macro_collector`·`company_master_collector`)는 `tools/`가 아니라 `services/collector/*.py` 모듈이다. 디렉토리 구조는 [03 §7.3](./03-company-data-collection-design.md#73-companycollector-구조)을 단일 출처로 한다. `tools/`에는 단계가 공유하는 도구만 둔다.

### save_tool 인터페이스

모든 단계가 동일한 `save_tool`을 통해 DB에 저장한다(URL 중복은 `ON CONFLICT DO NOTHING`).

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

## 5. DB 스키마 맵

전체 스키마는 각 소유 문서를 단일 출처로 한다. 본 문서는 **소유 맵**과 단계 간 계약인 **공통 상태 컬럼**만 정리한다.

### 테이블 소유 맵

| 테이블 | 정의 문서 |
|--------|----------|
| `news` | [02 §8.2](./02-news-collection-design.md#82-db-스키마-sqlalchemy) |
| `news_cluster` (클러스터링 산출물) | [02 §8.3](./02-news-collection-design.md#83-news_cluster-테이블-클러스터링-산출물) · 스코어 산식 [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어) |
| `disclosures` · `stock_prices` · `market_indicators` · `financial_statements` · `report_chunks` · `company_entities` | [03 §6](./03-company-data-collection-design.md#6-db-스키마) |
| `news_analysis` · `issue_docent` (L2) | [06 §17](./06-news-analysis-design.md#17-데이터-명세) |

### 파이프라인 공통 상태 컬럼 (단계 간 계약)

스키마 세부와 무관하게, 파이프라인은 다음 컬럼으로 단계 간 상태를 주고받는다.

| 컬럼 | 타입 | 의미 |
|------|------|------|
| `is_filtered` | Boolean | true = 전처리에서 분석 제외(24h·제목 중복) → 임베딩·분석 스킵 |
| `embedding` | Vector(768)¹, nullable | NULL = 임베딩 대기 (news에 유지) |
| `is_analyzed` | Boolean | false = 분석(L2) 대기 |

> 구 `preprocessed_at`(전처리 핸드오프 키)은 인메모리 전처리 전환으로 제거됐다 — 저장 시점이 곧 전처리 완료이므로 별도 상태 컬럼이 불필요하다(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)). 모델 컬럼은 마이그레이션 보류로 잔존하나 미사용이다.

> 복합 중요도 스코어는 **클러스터당** 값이라 news 상태 컬럼이 아니라 `news_cluster.importance`로 분리한다(grain 불일치 방지 → [02 §8.3](./02-news-collection-design.md#83-news_cluster-테이블-클러스터링-산출물)). `embedding`은 기사당이라 news에 남는다.

> ¹ 차원 기본값 768. **임베딩 모델은 미확정**이며 비교 테스트 후 결정한다(→ [05 §11](./05-embedding-clustering-design.md#11-미결-사항)). 모델 변경 시 차원이 바뀌면(`Vector(1024)` 등) 전 테이블 동시 변경 필요 → `EMBED_DIM` 환경 변수로 관리 권장(코드 네이밍 `EMBED_MODEL`/`EMBED_DIM`과 일치).

### 마이그레이션 전략

기존 `News` 모델과 기획서 스키마가 다르므로 Alembic으로 단계적 마이그레이션이 필요하다.

```bash
uv add alembic
alembic init alembic
alembic revision --autogenerate -m "add pipeline status fields"
alembic upgrade head
```

---

## 6. 에러 처리

**파이프라인 수준**은 Airflow가 Task 단위로 격리·재시도한다 — 한 단계가 실패하면 해당 Task만 재시도하고 미처리 레코드는 다음 run에서 재개된다(멱등). 상세는 [00 §7.3](./00-workflow-airflow.md#73-실패-처리재개-멘토-saga-피드백).

**도구 수준**은 외부 API 일시 실패에 대비해 지수 백오프 재시도를 공통 데코레이터로 둔다.

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
                except Exception:
                    if attempt == max_attempts - 1:
                        raise
                    await asyncio.sleep(2 ** attempt)   # 1s → 2s → 4s
        return wrapper
    return decorator
```

---

## 7. 디렉토리 구조

L1 단계·수집기·도구의 디렉토리 구조(정본). Airflow DAG 정의(`dags/`)는 [00 §11](./00-workflow-airflow.md#11-디렉토리-구조)을 참조한다.

```
services/
  ├── pipeline/                  ← 파이프라인 단계 + 러너 (단계 진입점, Phase 7)
  │   ├── news_collector.py      ← collect→preprocess→save 조립
  │   ├── company_collector.py
  │   ├── embedding_clusterer.py
  │   ├── news_analysis_agent.py ← L2 분석 에이전트 (→ 06 §18)
  │   └── runner.py              ← run_pipeline() (하이브리드 로컬 실행)
  │
  ├── collector/                 ← 수집기 + 도구
  │   ├── tools/                 ← cluster/score/save_tool 등
  │   ├── rss_collector.py       ← 국내 증권 RSS + investing.com 통합
  │   ├── dart_collector.py
  │   ├── stock_collector.py
  │   └── macro_collector.py
  │
  ├── preprocessor/              ← 전처리 구현 모듈 (인메모리 순수 함수)
  │   ├── news_preprocessor.py   ← run_preprocessing (HTML·URL·필터·제목중복)
  │   └── company_preprocessor.py ← DART 사업보고서 청크 분할
  │
  └── embedder/                  ← 임베딩·클러스터링 구현 모듈
      ├── news_embedder.py
      └── cluster.py
```

---

## 8. 통합 빌드 순서

전체 빌드는 **공통 기반 → 단계별 → 통합** 순으로 진행한다. 각 단계의 세부 Phase는 해당 문서의 로드맵을 따른다.

| 순서 | 작업 | 세부 |
|:---:|------|------|
| 0 | **공통 기반**: Alembic 마이그레이션, `AsyncSession`+`asyncpg` 전환, Neon pgvector 활성화 | 5장 |
| 1 | **수집기 + 전처리 + 도구** 구현 (rss/dart/stock/macro + `news_preprocessor` + `tools/`) | [02 P1](./02-news-collection-design.md#11-구현-로드맵), [03 P1](./03-company-data-collection-design.md#10-구현-로드맵), [04](./04-preprocessing-design.md#8-구현-로드맵) |
| 2 | **NewsCollector(수집→전처리→저장) / CompanyCollector** 조립 | [02 P2](./02-news-collection-design.md#11-구현-로드맵), [03 P2](./03-company-data-collection-design.md#10-구현-로드맵) |
| 3 | **EmbeddingClusterer** 구현 (⚠️ **임베딩 모델 비교·확정** 선행 → [05 §11](./05-embedding-clustering-design.md#11-미결-사항)) | [05](./05-embedding-clustering-design.md#10-구현-로드맵) |
| 4 | **러너 + Airflow DAG** (메인 + 보조) | [00 §8~§9](./00-workflow-airflow.md#8-dag-구현) |
| 5 | **통합 테스트** (end-to-end) | — |

> L2 분석(NewsAnalysisAgent → Issue Docent)은 [06](./06-news-analysis-design.md)에서 별도 담당한다.
