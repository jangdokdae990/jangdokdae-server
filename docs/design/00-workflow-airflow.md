# Airflow 워크플로우 오케스트레이션

> **작성자** Kim minkyoung · **작성일** 2026-06-08
>
> **범위** 파이프라인 전체의 실행 골격 — 스케줄링·의존성·실패 처리, 그리고 Airflow vs LangGraph 배치 기준

---

## 2계층 오케스트레이션 모델

장독대의 "한 번 실행하면 수집→전처리→임베딩→분석이 자동으로 이어지는" 자동화는 **성격이 다른 두 종류의 오케스트레이션**으로 나뉜다.

| 계층 | 도구 | 책임 | 문서 |
|------|------|------|------|
| **L1 파이프라인 오케스트레이션** | Airflow | 정형 단계(수집~임베딩)의 자동 연결·스케줄·재시도·관찰성 | **본 문서** |
| **L2 AI 에이전트 오케스트레이션** | LangGraph (슈퍼바이저-워커) | 분석→Issue Docent 단계 *내부*의 멀티 에이전트 추론·협업 | [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계) |

- **L1 = 자동화(automation)**: "다음에 무엇을 할지"가 고정돼 있다. 스케줄 트리거 1회 → 파이프라인 1회 완주.
- **L2 = 에이전트(agent)**: "다음에 무엇을 할지"를 LLM이 판단한다. **분석 단계 한 곳에만** 존재한다.
- 두 계층은 맞물린다 — **Airflow의 `analyze` Task 하나가 LangGraph 슈퍼바이저를 호출**한다. ("바깥 골격 + 내부 두뇌")

> "자동으로 이어지는 것"을 에이전트로 표현했지만, 정형 단계의 자동 연결은 **에이전트가 아니라 파이프라인 오케스트레이션**이다. 진짜 에이전트(LLM이 흐름을 판단)는 L2 분석 단계뿐이다. 각 단계를 L1/L2 중 어디에 둘지의 판단 기준은 [2장](#2-경계-기준--흐름-제어flow-control)에, 정형 단계(L1)의 내부 컴포넌트 설계는 [파이프라인 오케스트레이션](./01-pipeline-orchestration-design.md)에 있다.

본 문서(L1)는 **[기획]**(왜 Airflow인가·무엇을 오케스트레이션하는가)과 **[설계]**(어떻게 구현하는가) 두 부분으로 나뉜다.

## 목차

**[기획]**
- [1. 왜 Airflow인가](#1-왜-airflow인가)
- [2. 경계 기준 — 흐름 제어(Flow Control)](#2-경계-기준--흐름-제어flow-control)
- [3. 두 도구의 강점과 한계](#3-두-도구의-강점과-한계)
- [4. 파이프라인 7단계 배치 매핑](#4-파이프라인-7단계-배치-매핑)
- [5. 경계 케이스 해설](#5-경계-케이스-해설)

**[설계]**
- [6. 전체 구조](#6-전체-구조)
- [7. DAG 구성](#7-dag-구성)
- [8. DAG 구현](#8-dag-구현)
- [9. 파이프라인 러너 (하이브리드 로컬 실행)](#9-파이프라인-러너-하이브리드-로컬-실행)
- [10. Airflow를 선택한 이유 (vs APScheduler)](#10-airflow를-선택한-이유-vs-apscheduler)
- [11. 디렉토리 구조](#11-디렉토리-구조)

---

# [기획]

> **왜 하는가 · 무엇을 만들 것인가.**
> 이 부분은 파이프라인의 각 단계를 **Airflow와 LangGraph 중 어디에 배치하는지**, 그리고 **그 판단 기준**을 명문화한다.
> 멘토 피드백 핵심 질문 — **"컴포넌트 각각의 한계점을 명확히 정의했는가?"**([2026-06-02 피드백 1-1](../mentoring/2026-06-02-feedback.md))에 대한 직접 답이다.

## 1. 왜 Airflow인가

장독대 파이프라인은 `수집 → 전처리 → 임베딩·클러스터링 → 엔티티 추출 → 분석 → Issue Docent` 6단계로 이어진다. 이 흐름의 대부분은 **정해진 시각에, 정해진 순서로, 정형 작업**을 돌리는 일이다.

이런 작업에는 다음이 필요하다.

| 필요 | 설명 |
|------|------|
| 스케줄링 | 평일 09:00 / 15:30 / 16:30, 분기 첫날 등 시각 기반 실행 |
| 의존성·병렬 | "수집 2종 병렬 → 전처리 → 임베딩" 같은 단계 간 순서 보장 |
| 재시도 정책 | API 일시 실패 시 선언적 재시도 |
| 실행 이력·관망 | 어느 단계가 언제 성공/실패했는지 한눈에 (observability) |

LangGraph는 이 중 어느 것도 잘하지 못한다(→ [3장](#3-두-도구의-강점과-한계)). 반대로 Airflow는 이 영역에 특화돼 있다.
따라서 **파이프라인의 실행 골격은 Airflow가 잡고**, 추론이 필요한 일부 단계의 내부만 LangGraph 에이전트에 위임한다.

핵심은 **둘은 경쟁이 아니라 계층**이라는 점이다. Airflow가 바깥 골격(언제·어떤 순서로)을 잡고, 추론이 필요한 Task **내부**에서 LangGraph가 동작한다.

## 2. 경계 기준 — 흐름 제어(Flow Control)

경계를 가르는 기준은 **"LLM을 쓰느냐"가 아니다.**
**다음 단계로 갈 흐름을 LLM 판단으로 정하느냐**가 기준이다.

| 질문 | 예 → 배치 |
|------|----------|
| 다음에 무엇을 할지가 **LLM의 추론**으로 갈린다 (분기·반복) | **LangGraph** |
| 입력 → 출력이 고정돼 있고, 분기가 있어도 **정적**이다 (schedule, 고정 규칙) | **Airflow Task** |

핵심은 **정형 LLM 호출은 LangGraph가 아니다**라는 점이다.
임베딩 API 호출, 고정 스키마로 엔티티를 뽑는 LLM 호출은 "입력 → 출력"이 고정이므로 — LLM을 쓰더라도 — Airflow Task로 둔다.

```
한 단계를 만났을 때:

  이 단계 다음에 "무엇을 할지"가
  LLM 판단으로 달라지는가?
        │
   ┌────┴────┐
  YES        NO
   │          │
   ▼          ▼
LangGraph   분기가 있는가?
  노드        │
        ┌─────┴─────┐
       YES          NO
   (정적 분기)    (단순 순차)
        │            │
        ▼            ▼
   Airflow       Airflow
  분기 Task       Task
```

## 3. 두 도구의 강점과 한계

멘토 핵심 질문에 대한 직접 답 — **두 도구가 "못하는 것"을 명시**한다.

| | Airflow | LangGraph |
|---|---------|-----------|
| **잘하는 것** | 스케줄링, 재시도 정책, 실행 이력 UI, DAG 의존성·병렬, 분산 실행 | LLM 기반 동적 흐름 제어, 조건부 분기, 상태 누적, 추론 루프 |
| **못하는 것 (한계)** | LLM 판단에 따른 **동적 흐름**·**추론 루프** 불가. 분기는 사전 정의된 정적 분기만 | 스케줄링·재시도 이력·전체 파이프라인 **관망(observability)** 없음. cron·catchup 부재 |
| **그래서** | 정형·정적 단계의 **실행 골격** | 추론이 필요한 단계의 **내부 두뇌** |

두 도구는 **경쟁이 아니라 계층**이다. Airflow가 바깥 골격(언제·어떤 순서로)을 잡고, 추론이 필요한 Task **내부**에서 LangGraph가 동작한다.

## 4. 파이프라인 7단계 배치 매핑

CLAUDE.md 파이프라인 `수집 → 전처리 → 임베딩·클러스터링 → 엔티티 추출 → 분석 → Issue Docent` 전 단계를 [2장 기준](#2-경계-기준--흐름-제어flow-control)에 따라 배치한다.

| # | 단계 | 배치 | 흐름제어에 LLM 추론? | 근거 |
|---|------|------|:---:|------|
| 1 | **뉴스 수집** | **Airflow Task** | ❌ | `collect → save` **정적 순차**(수집 전용). 클러스터링·스코어링은 임베딩·클러스터링 단계(5번)로 분리 (→ [5.2](#52-뉴스-수집-정적-순차--airflow-task로-교정)) |
| 2 | **기업 수집** | **Airflow Task** | ❌ | `schedule`(morning/afternoon/macro/quarterly) 분기는 **정적**. DART·거시 API 호출은 입출력 고정 (주가·환율은 분석 시점 on-demand 조회) (→ [5.1](#51-기업-수집-기존-langgraph-설계--airflow-task로-교정)) |
| 3 | **전처리** | **Airflow Task** | ❌ | HTML 정제·타임존 정규화·날짜 필터·중복 제거 = **고정 규칙**. 분기 없음 |
| 4 | **임베딩** | **Airflow Task** | ❌ | Vertex AI 임베딩 API 호출. 입력(텍스트) → 출력(벡터)이 고정 |
| 5 | **클러스터링·스코어링** | **Airflow Task** | ❌ | 벡터 유사도(cosine) 클러스터링 + 복합 중요도 스코어(볼륨·속도 등). 결정적·정형, 분기·반복 없음 |
| 6 | **엔티티 추출** | **Airflow Task** | ❌ | **정형 LLM 호출** — 고정 스키마로 엔티티 추출. LLM을 쓰지만 흐름 분기는 없음 |
| 7 | **분석 → Issue Docent** | **LangGraph** | ✅ | 데이터 충분성 판단, RAG 엣지케이스(벡터DB에 없는 질의) 분기, 재시도·보강 루프. 다음 행동이 LLM 판단으로 갈림 |

> 6번 **엔티티 추출**이 핵심 경계 사례다. LLM을 호출하지만 "입력 → 고정 스키마 출력"이라 **흐름이 정적** → Airflow Task. "LLM = LangGraph"가 아님을 보여주는 대표 케이스.

## 5. 경계 케이스 해설

### 5.1 기업 수집: 기존 LangGraph 설계 → Airflow Task로 교정

[CompanyCollector](./03-company-data-collection-design.md#7-수집-파이프라인-아키텍처)는 본래 LangGraph 그래프로 설계됐다. 그러나 [2장 흐름 제어 기준](#2-경계-기준--흐름-제어flow-control)을 적용하면 — `schedule` 라우팅은 **LLM 추론이 아니라 사전 정의된 정적 분기**이고, 각 수집기 호출도 입출력이 고정이다. 추론 분기가 없으므로 **Airflow Task가 더 적합**하다.

- **교정 내용**: 기업 수집의 `route` 분기는 Airflow DAG의 정적 분기(또는 `BranchPythonOperator`)로 표현하고, 각 수집기는 독립 Task로 둔다.
- **01 문서와의 관계**: 01의 State·노드 구성은 "수집기 묶음"의 논리적 단위로는 유효하나, **실행 골격은 LangGraph 그래프가 아니라 Airflow Task 그룹**으로 본다.

### 5.2 뉴스 수집: 정적 순차 → Airflow Task로 교정

[NewsCollector](./02-news-collection-design.md#7-뉴스-수집-단계)는 과거 `collect → cluster → score → finalize` 그래프로 설계됐다. 그러나 클러스터·스코어는 클러스터(기사 그룹) 단위 평가라 임베딩·클러스터링 단계의 몫이고, 이를 분리하면 NewsCollector는 `collect → save` **수집 전용**으로 단순해진다. 분리 후에도 `cluster`(pgvector cosine)·`score`(복합 중요도 산술)는 결정적 연산이고 분기·반복이 없다. [2장 흐름 제어 기준](#2-경계-기준--흐름-제어flow-control)상 다음 행동을 LLM 추론으로 정하는 지점이 없으므로 수집·클러스터링·스코어링 모두 **Airflow Task가 적합**하다.

- **교정 내용**: 수집(`collect → save`)은 NewsCollector Task로, `cluster`·`score`는 임베딩·클러스터링 단계(EmbeddingClusterer) Task로 분리한다 (→ [05 §6·§8](./05-embedding-clustering-design.md#6-주요-이슈-선정--복합-중요도-스코어)).
- **폐기된 근거**: 과거 "수집 후 충분한가 판단 → 부족하면 추가 검색 루프"로 기술됐으나, 그런 LLM 판단 루프는 설계에 없다. 해당 근거는 폐기한다.

> **원칙 재확인**: 기준은 "LLM을 쓰는가"가 아니라 "다음 행동을 LLM 추론으로 정하는가"다. 뉴스 수집은 LLM 흐름 제어가 없어 — 그래프 형태로 묶이더라도 — Airflow Task로 둔다. (기업 수집 5.1과 동일한 교정.)

---

# [설계]

> **어떻게 구현할 것인가.**
> [기획] 부에서 정한 배치 기준을 실제 Airflow DAG·실행 구조로 구체화한다.

## 6. 전체 구조

```
Airflow DAG (dags/jangdokdae_pipeline.py)   ← 오케스트레이션: 스케줄·의존성·재시도·이력
   │  각 Task가 단계를 직접 호출 (단계 간 데이터는 공유 DB로 전달)
   │
   ├─ collect_news    → NewsCollector       (정적 순차)   ┐
   ├─ collect_company → CompanyCollector     (정적 분기)  │  (위 둘 병렬)
   │                                                      │ 공유 DB
   ├─ preprocess      → Preprocessor                      │ (PostgreSQL)
   ├─ embed_cluster   → EmbeddingClusterer                │
   └─ analyze         → NewsAnalysisAgent  (L2 에이전트)  ┘
                            │
                            ▼
                     Issue Docent  (→ 06 §18)
```

**핵심 원칙**: 단계끼리 직접 호출하지 않는다. **공유 DB를 통해서만 데이터를 전달**한다(상태 핸드오프). 오케스트레이션(실행 순서·병렬·재시도)은 **Airflow DAG가 전담**한다 — 별도 "마스터 오케스트레이터" 객체는 두지 않는다(→ [9장](#9-파이프라인-러너-하이브리드-로컬-실행)).
정형 단계(L1)의 내부 설계(State·노드·도구)는 [파이프라인 오케스트레이션](./01-pipeline-orchestration-design.md), 분석 단계(L2)의 멀티 에이전트 설계는 [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계)를 참조한다.

## 7. DAG 구성

**스케줄링·의존성·실패 처리는 Airflow DAG(Directed Acyclic Graph)가 담당**한다.
각 DAG Task가 해당 단계를 직접 호출한다(별도 오케스트레이터 객체 없음 → [9장](#9-파이프라인-러너-하이브리드-로컬-실행)).
DAG는 **메인 파이프라인 DAG**와 **보조 수집 DAG**로 나뉜다.

### 7.1 메인 파이프라인 DAG — "1 run = 전체 자동 완주"

수집→전처리→임베딩→분석을 한 DAG에 묶는다. **스케줄 트리거 1회 = 파이프라인 1회 완주.**

```
collect_news ∥ collect_company → preprocess → embed_cluster → analyze
```

| DAG | cron (KST) | 비고 |
|-----|-----------|------|
| `jangdokdae_pipeline` | `0 9 * * 1-5` (평일 09:00) | 장 시작 전 |
| `jangdokdae_pipeline` | `30 15 * * 1-5` (평일 15:30) | 장 마감 후 (동일 DAG의 두 번째 스케줄) |

> `analyze`는 L2 에이전트(슈퍼바이저-워커, → [06 §18](./06-news-analysis-design.md#18-newsanalysisagent-설계))를 호출하는 단일 Task다. Airflow에서 보면 정형 Task 하나이지만, 그 내부에서 LangGraph가 동작한다.

### 7.2 보조 수집 DAG — 다른 주기의 적재 전용

거시지표·사업보고서는 **주기가 달라** 메인에 합칠 수 없다. 적재만 하고, 다음 메인 run의 `embed`·`analyze`가 상태 핸드오프로 함께 흡수한다. (주가·환율은 적재하지 않고 분석 시점에 on-demand 조회 — [03 §4.3·§5.1](./03-company-data-collection-design.md#51-데이터-유형별-전략))

| DAG | cron (KST) | Task |
|-----|-----------|------|
| `jangdokdae_macro` | `0 16 1 * *` (매월 1일) | collect_macro (거시지표 ECOS 적재) |
| `jangdokdae_quarterly` | `0 9 1 1,4,7,10 *` (분기 첫날) | collect_reports → embed |

### 7.3 실패 처리·재개 (멘토 Saga 피드백)

- **단계 단위 재시도**: Airflow `retries`·`retry_delay`로 일시 실패(API 타임아웃 등)를 자동 재시도한다.
- **상태 기반 재개 = 멱등성**: 각 단계는 미처리 레코드(`embedding IS NULL`, `is_analyzed=false`)만 집어가므로, 중간 실패 후 재실행해도 **남은 것만** 처리된다. 뉴스 수집·전처리는 한 Task에서 정제본을 `ON CONFLICT(url) DO NOTHING`으로 멱등 저장한다. "원복(rollback)"보다 **"재개(resume)"**가 자연스럽다.
- **진짜 보상이 필요한 경우**(분석 중 외부 리소스 생성 실패 등)는 `analyze` 단계(L2) **내부**에서 처리한다.

## 8. DAG 구현

```python
# dags/jangdokdae_pipeline.py
import asyncio
from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonOperator
from services.pipeline.news_collector import NewsCollector
from services.pipeline.company_collector import CompanyCollector
from services.pipeline.preprocessor import Preprocessor
from services.pipeline.embedding_clusterer import EmbeddingClusterer
from services.pipeline.news_analysis_agent import NewsAnalysisAgent

# 각 Task가 단계를 직접 호출 (오케스트레이터 객체 없음)
def collect_news_task(**ctx):    asyncio.run(NewsCollector().run("scheduled"))
def collect_company_task(**ctx): asyncio.run(CompanyCollector().run("scheduled"))
def preprocess_task(**ctx):      asyncio.run(Preprocessor().run())
def embed_task(**ctx):           asyncio.run(EmbeddingClusterer().run())
def analyze_task(**ctx):         asyncio.run(NewsAnalysisAgent().run())   # L2 LangGraph 슈퍼바이저

with DAG(
    dag_id="jangdokdae_pipeline",
    schedule="0 9 * * 1-5",       # 09:00 — 15:30 run은 동일 DAG의 두 번째 스케줄(타임테이블)로 추가
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"retries": 2, "retry_delay": 60},
) as dag:

    t_news    = PythonOperator(task_id="collect_news",    python_callable=collect_news_task)
    t_company = PythonOperator(task_id="collect_company", python_callable=collect_company_task)
    t_prep    = PythonOperator(task_id="preprocess",      python_callable=preprocess_task)
    t_embed   = PythonOperator(task_id="embed_cluster",   python_callable=embed_task)
    t_analyze = PythonOperator(task_id="analyze",         python_callable=analyze_task)

    # 수집 병렬 → 전처리 → 임베딩 → 분석 (1 run = 전체 완주)
    [t_news, t_company] >> t_prep >> t_embed >> t_analyze
```

## 9. 파이프라인 러너 (하이브리드 로컬 실행)

오케스트레이션(실행 순서·병렬·재시도·이력)은 **Airflow DAG가 전담**한다. 별도의 "마스터 오케스트레이터" 객체는 두지 않는다 — [8장](#8-dag-구현)처럼 DAG의 각 Task가 해당 단계를 직접 생성·호출하기 때문이다.

> ⚠️ **MasterOrchestrator 제거 (2026-06-08)**: 과거 설계의 `MasterOrchestrator`는 단계 인스턴스를 모아 `run_collection`/`run_all` 등으로 묶는 헬퍼였다. 그러나 이는 Airflow DAG의 의존성·병렬·Task별 재시도와 **중복**되고("오케스트레이터가 둘"), `gather` 기반 병렬·에러 격리는 Airflow가 Task 단위로 더 잘 처리한다. 따라서 클래스는 삭제한다.

다만 **Airflow 없이 전체 파이프라인을 한 번에 돌리는 로컬·테스트 편의**(하이브리드, 인프라 0)를 위해 얇은 러너 함수 하나만 둔다.

```python
# services/pipeline/runner.py
"""하이브리드 로컬 실행용 러너. 운영 오케스트레이션은 Airflow DAG가 담당."""
import asyncio
from services.pipeline.news_collector import NewsCollector
from services.pipeline.company_collector import CompanyCollector
from services.pipeline.preprocessor import Preprocessor
from services.pipeline.embedding_clusterer import EmbeddingClusterer
from services.pipeline.news_analysis_agent import NewsAnalysisAgent


async def run_pipeline(schedule: str = "scheduled") -> None:
    """수집(병렬) → 전처리 → 임베딩 → 분석. 1회 호출 = 전체 파이프라인 완주."""
    await asyncio.gather(
        NewsCollector().run(schedule),
        CompanyCollector().run(schedule),
    )
    await Preprocessor().run()
    await EmbeddingClusterer().run()
    await NewsAnalysisAgent().run()        # L2 슈퍼바이저-워커


if __name__ == "__main__":
    asyncio.run(run_pipeline())            # python -m services.pipeline.runner
```

- **로컬·테스트**: `python -m services.pipeline.runner` → 전체 1회 완주 (인프라 0)
- **운영**: Airflow DAG가 동일 단계들을 스케줄·재시도·이력과 함께 실행([8장](#8-dag-구현))
- 단계 간 데이터는 공유 DB 상태 핸드오프 → 러너든 DAG든 동작은 동일

> 단계(파이프라인) 수준·도구 수준의 에러 처리 전략은 [01 문서 6장 에러 처리](./01-pipeline-orchestration-design.md#6-에러-처리)를 참조한다.

## 10. Airflow를 선택한 이유 (vs APScheduler)

| 항목 | APScheduler | **Airflow** |
|------|------------|------------|
| 실행 이력 UI | ❌ | ✅ Web UI (성공/실패/소요 시간) |
| 재시도 정책 | 수동 구현 | ✅ `retries`, `retry_delay` 선언적 |
| 태스크 병렬성 | 직접 코딩 | ✅ DAG 의존성으로 자동 처리 |
| 분산 실행 | ❌ | ✅ CeleryExecutor로 스케일아웃 |
| 실패 알림 | 없음 | ✅ Email/Slack 알림 내장 |
| 서버 재시작 후 | 스케줄 유실 | ✅ DB 기반으로 유지 |

## 11. 디렉토리 구조

Airflow DAG 정의는 프로젝트 루트의 `dags/`에 둔다. DAG가 호출하는 단계·도구의 디렉토리 구조는 [01 문서 7장](./01-pipeline-orchestration-design.md#7-디렉토리-구조)을 참조한다.

```
dags/                              ← Airflow DAG 정의
  ├── jangdokdae_pipeline.py     ← 메인: 평일 09:00·15:30 (수집→전처리→임베딩→분석, 1 run=전체 완주)
  ├── jangdokdae_macro.py        ← 보조: 매월 1일 (거시지표 ECOS 적재)
  └── jangdokdae_quarterly.py    ← 보조: 분기 첫날 (사업보고서 + 임베딩)

services/
  └── pipeline/runner.py         ← run_pipeline() (하이브리드 로컬 실행용; 운영은 Airflow DAG)
```
