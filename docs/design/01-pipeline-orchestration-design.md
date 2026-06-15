# 파이프라인 오케스트레이션 (L1 정형 단계 — 통합 개요)

> **작성자** Kim minkyoung · **작성일** 2026-05-28 (2026-06-12 핵심 압축 개정)
>
> **범위** L1 정형 파이프라인의 통합 개요 — 데이터 흐름·단계 인덱스·공유 도구·DB 스키마 맵·빌드 순서
>
> 각 단계의 상세는 02~05가 단일 출처. 실행 골격(스케줄·DAG·러너)은 [00](./00-workflow-airflow.md), 분석(L2)은 [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계).

---

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

단순 수집은 ① "오늘 중요한 뉴스"를 선정할 주체가 없고 ② 단계들이 서로의 실패를 모른다. 그래서:

- **선정은 EmbeddingClusterer가**: 클러스터를 복합 중요도로 평가해 `news_cluster`에 적재 (→ [05](./05-embedding-clustering-design.md)). 수집 단계는 수집·저장만.
- **오케스트레이션은 Airflow가**: 스케줄·의존성·재시도 전담, 별도 오케스트레이터 객체 없음 (→ [00](./00-workflow-airflow.md)).
- **LangGraph는 추론 단계에만**: 분석→Issue Docent만 LLM 분기가 필요 (→ [06](./06-news-analysis-design.md)). 나머지는 전부 Airflow Task.

> L1/L2 배치 기준과 7단계 매핑은 [00 §2·§4](./00-workflow-airflow.md#2-경계-기준--흐름-제어flow-control).

---

## 2. 전체 구조 & 데이터 핸드오프

```
Airflow DAG (각 Task가 단계를 직접 호출 → 00)
      ├── NewsCollector (수집→전처리→저장) ┐
      ├── CompanyCollector   (정적 분기)   │  공유 DB (PostgreSQL)
      └── EmbeddingClusterer               ┘
                ▼
          analyze (L2 → 06 §18) → Issue Docent
```

**핵심 원칙 — 상태 핸드오프**: 단계끼리 직접 호출하지 않고 **공유 DB의 상태 컬럼으로만** 데이터를 전달한다. 각 단계는 "미처리 레코드"만 집어가므로 느슨하게 결합되고, 부분 실패 후 재실행해도 남은 것만 처리된다(멱등). 순수 인메모리인 뉴스 전처리만 예외로 수집 노드 안에 합쳐 1회 저장한다(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)).

| 단계 | 읽는 조건 | 끝나면 |
|------|----------|--------|
| NewsCollector / CompanyCollector | — | INSERT 정제본 (`is_filtered`, `embedding=NULL`, `is_analyzed=false`) |
| EmbeddingClusterer | `is_filtered=FALSE AND embedding IS NULL` (임베딩) → 당일 창 + `is_duplicate=FALSE` (클러스터링) | `embedding` 채움 + `is_duplicate` soft 표시 + `news_cluster` UPSERT(`importance`) |
| NewsAnalysisAgent (L2) | `is_analyzed=false` (top_issues 인계) | Issue Docent 생성, `is_analyzed=true` |

> **"당일 수집분" 창**은 `settings.pipeline_window_hours`(기본 24h, KST)가 단일 출처 — dedup·클러스터링이 같은 값을 공유한다(창이 어긋나면 dedup 안 된 행이 클러스터에 섞임).

---

## 3. 파이프라인 단계 인덱스

| # | 단계 (클래스) | 역할 | 배치 | 상세 |
|---|------|------|------|:---:|
| 1 | **NewsCollector** | 수집 → 전처리(인메모리) → 저장 | Airflow Task (정적 순차) | [02](./02-news-collection-design.md#7-뉴스-수집-단계) · [04](./04-preprocessing-design.md) |
| 2 | **CompanyCollector** | 공시·거시·재무 수집 (`schedule` 정적 분기) | Airflow Task | [03](./03-company-data-collection-design.md#7-수집-파이프라인-아키텍처) |
| 3 | **EmbeddingClusterer** | 임베딩 → 중복 표시 → 클러스터링 → 이슈 선정 | Airflow Task | [05 §8](./05-embedding-clustering-design.md#8-embeddingclusterer-설계) |
| 4 | **NewsAnalysisAgent** | 분석 → Issue Docent (L2 추론) | LangGraph 슈퍼바이저-워커 | [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계) |

> 뉴스 전처리는 별도 Task가 아니라 NewsCollector 안의 인메모리 모듈(`news_preprocessor.run_preprocessing`)이다(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)).

---

## 4. 공유 도구 (Tools)

| 도구 | 경로 | 사용 단계 |
|------|------|-------------|
| `save_tool` | `services/collector/tools/save_tool.py` | **모든 단계 공유** — 테이블별 UPSERT 경계 (기본 DO NOTHING, `update_columns` 지정 시 DO UPDATE) |
| `company_loader` | `services/collector/tools/company_loader.py` | CompanyCollector (is_active 기업 로드) |
| `redact` | `services/collector/tools/redact.py` | 수집기 공통 (로그 API 키 마스킹) |
| `with_retry` | `services/collector/tools/with_retry.py` | 수집기 공통 (지수 백오프 1s→2s→4s) |
| 클러스터링·스코어 | `services/embedder/cluster.py` · `score.py` | EmbeddingClusterer (당초 tools/ 계획에서 embedder/ 모듈로 구현) |

> **수집기는 도구가 아니다**: 개별 수집기(`rss_collector` 등)는 `services/collector/*.py` 모듈. `tools/`에는 단계가 공유하는 도구만 둔다.

---

## 5. DB 스키마 맵

### 테이블 소유 맵

| 테이블 | 정의 문서 |
|--------|----------|
| `news` | [02 §8.2](./02-news-collection-design.md#82-db-스키마-sqlalchemy) |
| `news_cluster` | [02 §8.3](./02-news-collection-design.md#83-news_cluster-테이블-클러스터링-산출물) · 스코어 산식 [05 §6](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어) |
| `disclosures` · `stock_prices` · `market_indicators` · `financial_statements` · `report_chunks` · `company_entities` | [03 §6](./03-company-data-collection-design.md#6-db-스키마) |
| `news_analysis` · `issue_docent` (L2) | [06 §17](./06-news-analysis-design.md#17-데이터-명세) |

### 파이프라인 공통 상태 컬럼 (단계 간 계약)

| 컬럼 | 타입 | 의미 |
|------|------|------|
| `is_filtered` | Boolean | true = 전처리 탈락(24h·제목 중복) → 임베딩·분석 스킵 |
| `embedding` | Vector(768)¹, nullable | NULL = 임베딩 대기 |
| `is_duplicate` | Boolean | true = 임베딩 유사도(≥0.95) 근접 중복 → 클러스터링·분석 제외 (soft flag, → [05 §4.2](./05-embedding-clustering-design.md#42-중복-제거-cosine--095--하드-삭제가-아니라-soft-flag)) |
| `is_analyzed` | Boolean | false = 분석(L2) 대기 |

- 구 `preprocessed_at`은 인메모리 전처리 전환으로 **제거 완료**(2026-06-11 마이그레이션) — 저장 시점이 곧 전처리 완료.
- 복합 중요도는 클러스터당 값이라 `news_cluster.importance`로 분리(grain 불일치 방지). `embedding`은 기사당이라 news에 남는다.
- ¹ **모델 확정: `gemini-embedding-001`(768)** — 3축 평가 전 축 1위(→ [평가 보고서](../evaluation/00-embedding-model-evaluation.md)). `EMBED_MODEL`/`EMBED_DIM` 환경 변수 관리, 1024 모델 전환 시 전 테이블 동시 마이그레이션 필요.

### 마이그레이션

Alembic으로 관리한다. baseline(e91033167c44) 이후 `is_duplicate` 추가 → `preprocessed_at` 제거 → `news_cluster`·인덱스 보강 → 멱등 유니크 제약 → `created_at` 인덱스까지 적용 완료(2026-06-11 기준 head 일치, ORM↔DB 드리프트 0).

---

## 6. 에러 처리

- **파이프라인 수준**: Airflow가 Task 단위 격리·재시도(`retries=2`). 실패 후 재실행은 상태 컬럼 덕에 "재개"가 된다(멱등) → [00 §7.3](./00-workflow-airflow.md#73-실패-처리재개-멘토-saga-피드백).
- **도구 수준**: 외부 API 일시 실패는 `with_retry` 지수 백오프(1s→2s→4s)로 방어. Airflow 재시도와 별개의 층.

---

## 7. 디렉토리 구조

```
services/
  ├── pipeline/                  ← 단계 진입점 + 러너
  │   ├── news_collector.py      ← collect→preprocess→save 조립
  │   ├── company_collector.py   ← schedule 정적 분기
  │   ├── embedding_clusterer.py ← embed ∥ → dedup → cluster → score
  │   ├── runner.py              ← run_pipeline() 하이브리드 로컬 실행
  │   └── news_analysis_agent.py ← L2 (미구현 → 06 §18)
  ├── collector/                 ← 수집기 + tools/ (save·loader·redact·retry)
  ├── preprocessor/              ← news_preprocessor(인메모리) · company_preprocessor · deduplicator(유사도 soft-flag)
  └── embedder/                  ← embedding_client · news/report_embedder · cluster · score
```

Airflow DAG(`dags/`)는 [00 §11](./00-workflow-airflow.md#11-디렉토리-구조) 참조.

---

## 8. 통합 빌드 순서

| 순서 | 작업 | 상태 |
|:---:|------|:---:|
| 0 | 공통 기반: Alembic·AsyncSession·pgvector | ✅ |
| 1 | 수집기 + 전처리 + 도구 | ✅ |
| 2 | NewsCollector / CompanyCollector 조립 | ✅ |
| 3 | EmbeddingClusterer (모델 확정 선행 → [05 §11](./05-embedding-clustering-design.md#11-미결-사항)) | ✅ (2026-06-11, 실완주 검증) |
| 4 | 러너 + Airflow DAG | 러너 ✅ · DAG ⬜ |
| 5 | 통합 테스트 (end-to-end) | 1차 실측 ✅ · 분석 연결 후 재검증 ⬜ |

> L2 분석(NewsAnalysisAgent → Issue Docent)은 [06](./06-news-analysis-design.md)에서 별도 담당.
