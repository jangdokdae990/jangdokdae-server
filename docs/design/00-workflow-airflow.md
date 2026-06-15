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

**[기초]**

- [0. Airflow 기초 — 무엇이고, 왜 필요하고, 어떻게 생겼는가](#0-airflow-기초--무엇이고-왜-필요하고-어떻게-생겼는가)

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
- [12. 배포·실행 환경](#12-배포실행-환경)

---

# [기초]

> **Airflow 자체에 대한 배경지식.** 장독대 설계 결정([기획]·[설계])을 읽기 전에 필요한 최소한의 Airflow 이해를 정리한다. 이미 Airflow를 아는 독자는 [1장](#1-왜-airflow인가)으로 건너뛰어도 된다.
>
> 📘 이 §0은 **설계 진입용 압축 요약**이다. 개념·설치·배포를 처음부터 풀어 익히려면 → [Airflow 핵심 개념 가이드](../guide/00-airflow-essentials.md).

## 0. Airflow 기초 — 무엇이고, 왜 필요하고, 어떻게 생겼는가

### 0.1 Airflow란

**Apache Airflow는 워크플로우를 파이썬 코드로 정의하고, 스케줄에 따라 실행하고, 상태를 모니터링하는 오픈소스 오케스트레이션 플랫폼**이다.

핵심 철학은 **"Workflow as Code"** — 워크플로우를 GUI나 XML이 아니라 **파이썬 코드(DAG 파일)로 선언**한다. 그래서 버전 관리(git)·코드 리뷰·테스트가 일반 코드와 동일하게 적용되고, 동적 생성(반복문으로 Task 생성)도 가능하다.

> 한 줄 요약: **"cron + 의존성 그래프 + 재시도 + 실행 이력 UI"를 코드로 선언하는 플랫폼.**

### 0.2 왜 필요한가 — cron만으로 안 되는 이유

단순히 "정해진 시각에 스크립트 실행"이라면 cron으로 충분하다. 문제는 파이프라인이 **여러 단계의 의존 관계**가 되는 순간부터다.

| cron의 한계 | 무슨 일이 생기나 | Airflow의 해법 |
|------|------|------|
| **의존성 표현 불가** | "수집이 끝나면 임베딩"을 시간 간격 추정으로 흉내 (`09:00 수집, 09:30 임베딩`) → 수집이 늦어지면 빈 데이터로 임베딩 실행 | DAG 의존성(`수집 >> 임베딩`)으로 **선행 성공 시에만** 실행 |
| **부분 실패 처리 부재** | 3단계 중 2단계가 죽으면? 전체 재실행 or 수동 복구 | 실패한 Task만 **선언적 재시도**(`retries`), 성공한 단계는 건너뜀 |
| **실행 이력 없음** | "어제 새벽 적재가 왜 비었지?"를 로그 grep으로 추적 | Web UI에서 run별 성공/실패/소요시간/로그 한눈에 (observability) |
| **과거 구간 재처리(backfill) 수동** | 장애로 3일치가 빠지면 날짜 바꿔가며 수동 실행 | `backfill` 명령으로 기간 지정 일괄 재실행 |
| **알림 없음** | 실패를 다음 날 발견 | 실패 시 콜백·알림 내장 |

요컨대 cron은 **"언제"**만 알고, Airflow는 **"언제 + 어떤 순서로 + 실패하면 어떻게"**까지 안다. 장독대 파이프라인(수집 2종 병렬 → 임베딩·클러스터링 → 분석)이 정확히 이 의존성·부분 실패 문제를 갖는다 — 구체적 도구 비교는 [10장](#10-airflow를-선택한-이유-vs-apscheduler)을 참조한다.

### 0.3 기본 아키텍처

Airflow 3.x는 역할별로 분리된 **서비스들의 모임**이다. 각 서비스는 메타데이터 DB를 중심으로 통신한다.

```
                    ┌──────────────┐
   DAG 파일(dags/) → │ DAG Processor │ ─ 파싱·직렬화 ─┐
                    └──────────────┘               ▼
                    ┌──────────────┐        ┌─────────────┐
        사용자 ←──── │  API Server  │ ←────→ │ Metadata DB │ ← 모든 상태의 단일 출처
       (Web UI)     └──────────────┘        │ (PostgreSQL) │   (run·task 상태, 스케줄, 이력)
                    ┌──────────────┐        └─────────────┘
                    │  Scheduler   │ ─ "실행할 때가 된 Task" 판정 ─→ Executor → ┌────────┐
                    └──────────────┘                                          │ Worker │ ← Task 실제 실행
                    ┌──────────────┐                                          └────────┘
                    │  Triggerer   │ ← 비동기 대기(deferrable) 전담
                    └──────────────┘
```

| 컴포넌트 | 역할 | 장독대 관점 |
|------|------|------|
| **Scheduler** | 심장. DAG의 스케줄·의존성을 보고 "지금 실행할 Task"를 결정 | 평일 09:00/15:30 트리거 판정 |
| **DAG Processor** | `dags/` 폴더의 파이썬 파일을 주기적으로 파싱해 DB에 직렬화 (3.x에서 별도 서비스로 분리) | `dags/jangdokdae_*.py` 3개 파싱 |
| **API Server** | Web UI·REST API 제공. Task↔DB 사이의 중개자 (3.x에서 webserver를 대체) | 실행 이력·로그 확인 창구 |
| **Worker / Executor** | Task를 실제 실행. Executor가 실행 방식을 결정 — LocalExecutor(단일 머신 프로세스)부터 Celery/Kubernetes(분산)까지 | 시연 규모는 **LocalExecutor로 충분** |
| **Triggerer** | 외부 이벤트 대기(deferrable operator)를 워커 점유 없이 비동기 처리 | 당장 미사용 (시각 기반 스케줄만) |
| **Metadata DB** | 모든 상태(run·task instance·스케줄·이력)의 단일 출처 | Airflow 전용 DB — 장독대 데이터 DB(Neon)와 **별개** |

> **Airflow 3의 보안 변화**: Task 코드가 메타데이터 DB에 직접 접근하는 것이 차단됐다(Task SDK·API Server 경유). 장독대 Task는 어차피 자체 DB(Neon)만 만지므로 영향 없다 — 오히려 "Airflow의 상태 저장소와 우리 데이터 저장소는 별개"라는 경계가 명확해진다.

### 0.4 핵심 개념

| 개념 | 정의 | 장독대 대응 |
|------|------|------|
| **DAG** (Directed Acyclic Graph) | 워크플로우 1개 = Task들의 방향 비순환 그래프. 순환이 없어야 "언젠가 끝남"이 보장된다 | `jangdokdae_pipeline`·`jangdokdae_macro`·`jangdokdae_quarterly` 3개 |
| **Task / Operator** | Task = 실행 단위 1개. Operator는 Task의 템플릿(PythonOperator, BashOperator 등) | 각 단계(NewsCollector 등)를 PythonOperator로 호출 (→ [8장](#8-dag-구현)) |
| **Task Instance** | 특정 run에서의 Task 실행 1회. 상태(success/failed/retry)를 가진다 | 09:00 run의 `collect_news` 1회 |
| **DAG Run** | DAG의 실행 1회 (스케줄 또는 수동 트리거) | "1 run = 전체 완주" (→ [7.1](#71-메인-파이프라인-dag--1-run--전체-자동-완주)) |
| **schedule / catchup** | cron 표현식으로 주기 정의. `catchup=True`면 과거 미실행 구간을 소급 실행 | `0 9 * * 1-5`. **catchup=False** — 뉴스는 과거 소급이 무의미(24h 창) |
| **backfill** | 지정 기간의 run을 일괄 (재)실행 | 거시지표·공시는 자체 backfill 스크립트로 이미 처리 — Airflow backfill과 역할 중복 없음 |
| **retries / retry_delay** | Task 실패 시 선언적 재시도 | `retries=2, retry_delay=60` (→ [7.3](#73-실패-처리재개-멘토-saga-피드백)) |
| **XCom** | Task 간 소량 데이터 전달 (메타데이터 DB 경유) | **의도적으로 최소화** — 단계 간 데이터는 공유 DB 상태 컬럼으로 전달하고, XCom엔 카운트·신호만 (→ [01 §2](./01-pipeline-orchestration-design.md)) |
| **Connection / Hook** | 외부 시스템 접속 정보의 중앙 관리 + 접속 클라이언트 | 미사용 — 접속 정보는 기존 `.env`/settings 체계 유지 (도구 이원화 방지) |
| **Sensor / Deferrable** | "조건이 충족될 때까지 대기"하는 특수 Task | 당장 미사용 — 시각 기반 스케줄로 충분 |
| **멱등성** (Airflow가 전제하는 성질) | 같은 run을 재실행해도 결과가 같아야 재시도가 안전하다 | 전 단계 ON CONFLICT·상태 컬럼으로 보장 — 재시도는 "원복"이 아니라 "재개" (→ [7.3](#73-실패-처리재개-멘토-saga-피드백)) |

> **개념 간 관계 한 줄**: DAG가 Task를 묶고, Scheduler가 DAG Run을 만들고, Executor가 Task Instance를 Worker에서 돌리고, 상태는 전부 Metadata DB에 남는다.

### 0.5 기업·실무 활용 사례

Airflow가 실무에서 쓰이는 대표 패턴과 공개된 사례들이다. **공통점: "여러 소스에서 모아 → 가공 → 적재 → 후속 작업"의 정형 파이프라인을 스케줄로 돌린다** — 장독대 파이프라인과 동형이다.

| 활용 패턴 | 설명 | 공개 사례 |
|------|------|------|
| **ETL / ELT 데이터 파이프라인** (가장 고전적) | 여러 소스 → 변환 → 데이터 웨어하우스(Snowflake·BigQuery 등) 적재. 일/시간 단위 스케줄 | **Airbnb**(탄생 배경 — 사내 전 데이터 파이프라인), 국내 다수 테크 기업(쏘카·라인 등)의 데이터 플랫폼 기술 블로그 |
| **ML/AI 파이프라인** | 데이터 준비 → 학습 → 평가 → 배포 주기 실행. State of Airflow 2025 기준 관리형(Astro) 사용자의 **55%가 ML/AI 워크로드**에 사용 | 추천 시스템 재학습, 피처 스토어 갱신 |
| **대규모 멀티테넌트 오케스트레이션** | 수천 개 DAG를 단일 플랫폼에서 운영 | **Shopify**(수천 DAG 운영 경험 공개), **Pinterest**(자체 워크플로우 플랫폼의 기반) |
| **리포팅·집계 자동화** | 일·주·월 단위 지표 집계와 리포트 발송 | 매출 마감, 일일 대시보드 갱신 |
| **외부 API 주기 수집** | 외부 API를 정해진 주기로 폴링해 적재, 실패 시 재시도 | **장독대가 정확히 이 패턴** — RSS·DART·ECOS 수집 → 임베딩 → 분석 |

장독대 기준으로 보면: 우리는 "외부 API 주기 수집 + ETL" 패턴의 소형 사례이고, `analyze` Task 내부에 LLM 에이전트(L2)가 들어가는 점이 최근 추세(Airflow 위에 AI 워크로드)와 정확히 겹친다.

**참고 자료**

- [Airflow Architecture Overview (공식, 3.x)](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html)
- [Airflow Components (Astronomer)](https://www.astronomer.io/docs/learn/airflow-components)
- [State of Airflow 2025 (Astronomer — 채택 규모·ML 워크로드 통계)](https://www.astronomer.io/blog/state-of-airflow-2025-unleashing-the-future-of-data-orchestration/)
- [Apache Airflow 프로젝트 연혁 (공식)](https://airflow.apache.org/docs/apache-airflow/stable/project.html)

---

# [기획]

> **왜 하는가 · 무엇을 만들 것인가.**
> 이 부분은 파이프라인의 각 단계를 **Airflow와 LangGraph 중 어디에 배치하는지**, 그리고 **그 판단 기준**을 명문화한다.
> 멘토 피드백 핵심 질문 — **"컴포넌트 각각의 한계점을 명확히 정의했는가?"**([2026-06-02 피드백 1-1](../mentoring/2026-06-02-feedback.md))에 대한 직접 답이다.

## 1. 왜 Airflow인가

장독대 파이프라인 대부분은 **정해진 시각에, 정해진 순서로 도는 정형 작업**이다 — 필요한 것은 스케줄링(평일 09:00/15:30 등), 의존성·병렬, 선언적 재시도, 실행 이력(observability)이고, 이 영역의 특화 도구가 Airflow다. LangGraph는 이 중 어느 것도 잘하지 못한다(→ [3장](#3-두-도구의-강점과-한계)).

**둘은 경쟁이 아니라 계층**이다 — Airflow가 바깥 골격(언제·어떤 순서로)을 잡고, 추론이 필요한 Task **내부**에서 LangGraph가 동작한다.

## 2. 경계 기준 — 흐름 제어(Flow Control)

경계 기준은 **"LLM을 쓰느냐"가 아니라 "다음 단계로 갈 흐름을 LLM 판단으로 정하느냐"**다.

| 질문 | 예 → 배치 |
|------|----------|
| 다음에 무엇을 할지가 **LLM의 추론**으로 갈린다 (분기·반복) | **LangGraph** |
| 입력 → 출력이 고정, 분기가 있어도 **정적** (schedule, 고정 규칙) | **Airflow Task** |

따라서 **정형 LLM 호출은 LangGraph가 아니다** — 임베딩 API, 고정 스키마 엔티티 추출은 LLM을 쓰더라도 흐름이 정적이므로 Airflow Task다.

## 3. 두 도구의 강점과 한계

멘토 핵심 질문("컴포넌트 각각의 한계를 정의했는가")에 대한 직접 답 — **못하는 것**을 명시한다.

| | Airflow | LangGraph |
|---|---------|-----------|
| **잘하는 것** | 스케줄링, 재시도 정책, 실행 이력 UI, DAG 의존성·병렬, 분산 실행 | LLM 기반 동적 흐름 제어, 조건부 분기, 상태 누적, 추론 루프 |
| **못하는 것** | LLM 판단 **동적 흐름·추론 루프** 불가 — 분기는 정적 분기만 | 스케줄링·재시도 이력·파이프라인 **observability** 없음. cron·catchup 부재 |
| **그래서** | 정형 단계의 **실행 골격** | 추론 단계의 **내부 두뇌** |

## 4. 파이프라인 7단계 배치 매핑

CLAUDE.md 파이프라인 `수집 → 전처리 → 임베딩·클러스터링 → 엔티티 추출 → 분석 → Issue Docent` 전 단계를 [2장 기준](#2-경계-기준--흐름-제어flow-control)에 따라 배치한다.

| # | 단계 | 배치 | 흐름제어에 LLM 추론? | 근거 |
|---|------|------|:---:|------|
| 1 | **뉴스 수집** | **Airflow Task** | ❌ | `collect → save` **정적 순차**(수집 전용). 클러스터링·스코어링은 임베딩·클러스터링 단계(5번)로 분리 (→ [5.2](#52-뉴스-수집-정적-순차--airflow-task로-교정)) |
| 2 | **기업 수집** | **Airflow Task** | ❌ | `schedule`(morning/afternoon/macro/quarterly) 분기는 **정적**. DART·거시 API 호출은 입출력 고정 (주가·환율은 분석 시점 on-demand 조회) (→ [5.1](#51-기업-수집-langgraph--airflow-task로-교정)) |
| 3 | **전처리** | **Airflow Task** | ❌ | HTML 정제·타임존 정규화·날짜 필터·중복 제거 = **고정 규칙**. 분기 없음 |
| 4 | **임베딩** | **Airflow Task** | ❌ | Vertex AI 임베딩 API 호출. 입력(텍스트) → 출력(벡터)이 고정 |
| 5 | **클러스터링·스코어링** | **Airflow Task** | ❌ | 벡터 유사도(cosine) 클러스터링 + 복합 중요도 스코어(볼륨·속도 등). 결정적·정형, 분기·반복 없음 |
| 6 | **엔티티 추출** | **Airflow Task** | ❌ | **정형 LLM 호출** — 고정 스키마로 엔티티 추출. LLM을 쓰지만 흐름 분기는 없음 |
| 7 | **분석 → Issue Docent** | **LangGraph** | ✅ | 데이터 충분성 판단, RAG 엣지케이스(벡터DB에 없는 질의) 분기, 재시도·보강 루프. 다음 행동이 LLM 판단으로 갈림 |

> 6번 **엔티티 추출**이 핵심 경계 사례다. LLM을 호출하지만 "입력 → 고정 스키마 출력"이라 **흐름이 정적** → Airflow Task. "LLM = LangGraph"가 아님을 보여주는 대표 케이스.

## 5. 경계 케이스 해설

과거 LangGraph로 설계됐다가 [2장 기준](#2-경계-기준--흐름-제어flow-control)으로 Airflow Task로 교정한 두 사례 — 기준은 항상 "다음 행동을 LLM 추론으로 정하는가"다.

### 5.1 기업 수집: LangGraph → Airflow Task로 교정

`schedule`(morning/afternoon/macro/quarterly) 라우팅은 LLM 추론이 아니라 **사전 정의된 정적 분기**이고 각 수집기 호출도 입출력 고정 → Airflow Task. 01의 State·노드 구성은 논리 단위로는 유효하되, 실행 골격은 Airflow Task 그룹이다.

### 5.2 뉴스 수집: 정적 순차 → Airflow Task로 교정

과거 `collect → cluster → score → finalize` 그래프 설계에서 — 클러스터·스코어는 클러스터(기사 그룹) 단위 평가라 **임베딩·클러스터링 단계(05)의 몫**으로 분리하고, NewsCollector는 `collect → save` 수집 전용으로 단순화했다. 분리 후 남는 연산도 전부 결정적이라 Airflow Task. (과거의 "부족하면 추가 검색 루프" 근거는 설계에 없는 가공의 루프라 폐기.)

---

# [설계]

> **어떻게 구현할 것인가.**
> [기획] 부에서 정한 배치 기준을 실제 Airflow DAG·실행 구조로 구체화한다.

## 6. 전체 구조

```
Airflow DAG (dags/jangdokdae_pipeline.py)   ← 스케줄·의존성·재시도·이력
   │  각 Task가 단계를 직접 호출 (단계 간 데이터는 공유 DB로 전달)
   │
   ├─ collect_news    → NewsCollector (수집→전처리 인메모리→저장) ┐ (병렬)
   ├─ collect_company → CompanyCollector (정적 분기)              │ 공유 DB
   ├─ embed_cluster   → EmbeddingClusterer                        │ (PostgreSQL)
   └─ analyze         → NewsAnalysisAgent (L2 에이전트)           ┘
                            ▼
                     Issue Docent  (→ 06 §18)
```

**핵심 원칙**: 단계끼리 직접 호출하지 않고 **공유 DB 상태 핸드오프**로만 전달(→ [01 §2](./01-pipeline-orchestration-design.md#2-전체-구조--데이터-핸드오프)). 오케스트레이션은 **Airflow DAG가 전담** — 별도 "마스터 오케스트레이터" 객체는 두지 않는다(→ [9장](#9-파이프라인-러너-하이브리드-로컬-실행)). 전처리는 별도 Task가 아니라 NewsCollector 내부 인메모리 모듈이다(→ [04 §1.2](./04-preprocessing-design.md#12-전처리의-위치--수집전처리저장을-한-흐름으로)).

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
# dags/jangdokdae_pipeline.py — 개념 골격 (3-Task; 실제 구현은 venv 격리로
#   ExternalPythonOperator 사용 → §12.3. 아래는 흐름을 보이는 단순화 버전이다.)
import asyncio
import pendulum
from airflow.sdk import DAG                                    # 3.x Task SDK 경로
from airflow.providers.standard.operators.python import PythonOperator
from airflow.timetables.trigger import MultipleCronTriggerTimetable
from app.db.base import AsyncSessionLocal
from services.pipeline.news_collector import NewsCollector
from services.pipeline.company_collector import CompanyCollector
from services.pipeline.embedding_clusterer import EmbeddingClusterer

def _schedule_for(context):                      # 09:00 run=morning, 15:30 run=afternoon
    hour = context["logical_date"].in_timezone("Asia/Seoul").hour
    return "morning" if hour < 12 else "afternoon"

async def _news(schedule):                       # AsyncSession은 Task별 독립 세션
    async with AsyncSessionLocal() as db:
        await NewsCollector().run(db, schedule)

async def _embed():
    async with AsyncSessionLocal() as db:
        await EmbeddingClusterer().run(db)

with DAG(
    dag_id="jangdokdae_pipeline",
    # 평일 09:00·15:30 KST 두 트리거. Airflow 3.x는 한 DAG에 cron 하나라
    # MultipleCronTriggerTimetable로 두 cron을 묶는다(분이 달라 단일 cron 불가).
    schedule=MultipleCronTriggerTimetable(
        "0 9 * * 1-5", "30 15 * * 1-5", timezone="Asia/Seoul"
    ),
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Seoul"),
    catchup=False,                 # 뉴스는 과거 소급 무의미(24h 창)
    default_args={"retries": 2, "retry_delay": pendulum.duration(seconds=60)},
) as dag:
    t_news    = PythonOperator(task_id="collect_news",
                               python_callable=lambda **c: asyncio.run(_news(_schedule_for(c))))
    t_company = PythonOperator(task_id="collect_company",
                               python_callable=lambda **c: asyncio.run(CompanyCollector().run(_schedule_for(c))))
    t_embed   = PythonOperator(task_id="embed_cluster",
                               python_callable=lambda: asyncio.run(_embed()))
    # TODO: analyze Task — NewsAnalysisAgent(06, L2) 구현 후 t_embed >> t_analyze 추가
    [t_news, t_company] >> t_embed
```

## 9. 파이프라인 러너 (하이브리드 로컬 실행)

운영 오케스트레이션은 Airflow DAG가 전담하되, **Airflow 없이 전체를 1회 완주하는 로컬·테스트 편의**(인프라 0)로 얇은 러너를 둔다 — `services/pipeline/runner.py`에 **구현 완료**(2026-06-11, 실완주 검증).

- **로컬·테스트**: `python -m services.pipeline.runner [schedule]` → (수집 ∥) → 임베딩·클러스터링 1회 완주. 분석(06)은 TODO.
- **운영**: Airflow DAG가 동일 단계를 스케줄·재시도·이력과 함께 실행([8장](#8-dag-구현)). 단계 간 데이터는 공유 DB 핸드오프라 러너든 DAG든 동작 동일.

> ⚠️ **MasterOrchestrator 제거 (2026-06-08)**: 과거의 단계 묶음 헬퍼는 Airflow DAG의 의존성·병렬·재시도와 중복("오케스트레이터가 둘")이라 삭제했다. 에러 처리 전략은 [01 §6](./01-pipeline-orchestration-design.md#6-에러-처리).

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

Dockerfile                         ← apache/airflow 베이스 + 코어 의존성 (→ §12.3)
docker-compose.yaml                ← postgres(metadata)+scheduler+apiserver+dag-processor (LocalExecutor)
.dockerignore                      ← .venv·__pycache__·logs·tests 등 빌드 컨텍스트 제외

services/
  └── pipeline/runner.py         ← run_pipeline() (하이브리드 로컬 실행용; 운영은 Airflow DAG)
```

---

## 12. 배포·실행 환경

<callout icon="🚢" color="brown_bg">
 지금까지(§6~§11)는 "무엇을 어떤 순서로 실행하는가"였다. 이 장은 **"그 Airflow를 어디에 어떤 형태로 띄우는가"** — design 00이 그동안 비워뒀던 배포·실행 환경을 채운다. 핵심 결정은 **데모와 운영을 한 가지 구성(docker-compose)으로 잇는 것**이다.
</callout>

### 12.1 배포 옵션 비교

Airflow는 "컨테이너 위에서 돌린다"는 점은 어디서나 같지만, **그 컨테이너를 누가·어디서 띄우느냐**가 갈린다. 시연 규모(LocalExecutor면 충분, → [0.3](#03-기본-아키텍처))를 기준으로 네 갈래를 비교한다.

| 방식 | 대략 비용 | 운영 복잡도 | 데모↔운영 연속성 | 적합 규모 |
|------|----------|------------|-----------------|----------|
| **로컬 docker-compose** | 0 | 낮음 | 이미지·DAG 그대로 재사용 | 데모·발표 |
| **Compute Engine + docker-compose** | 메모리 4GB+ VM(e2-medium~) 월 $25~50 | 중 (VM·재시작 직접 관리) | 데모 compose를 **그대로** 올림 | 소규모 운영 |
| **GKE + 공식 Helm chart** | 클러스터 비용 + 운영 공수 | 높음 | 이미지 재사용, K8s 매니페스트 별도 작성 | 중·대규모 |
| **Cloud Composer (관리형)** | 월 $300~400+ | 낮음 (위탁) | DAG만 업로드 (인프라 추상화) | 본격 운영 |

> 공식 docker-compose는 Airflow가 **직접 제공**하지만 문서에 *"learning/exploration용, 프로덕션 아님"*으로 명시돼 있다. 프로덕션 자체 호스팅 표준은 **K8s + Helm**, 관리형 표준은 **Composer/MWAA/Astronomer**다 — 모두 컨테이너 기반이라는 점은 같고, docker-compose는 그 입문·시연 버전이다.

### 12.2 선택: docker-compose 중심

장독대는 **로컬 docker-compose를 정본**으로 삼는다.

- **데모**: 로컬에서 `docker compose up` → 스케줄·의존성·재시도·Web UI까지 실제 Airflow로 시연.
- **운영(소규모)**: **동일한 compose를 GCP Compute Engine VM에 그대로 올린다**(→ [12.4](#124-운영-승격-경로)). 이미지·DAG·환경이 데모와 동일하므로 "데모에서 됐는데 운영에서 안 되는" 간극이 없다.
- **확장**: 트래픽·DAG가 커지면 **Cloud Composer(관리형)** 또는 **GKE+Helm**으로 승격 — DAG 코드는 그대로 두고 실행 환경만 교체.

**근거**

1. **한 구성이 데모·소규모 운영을 모두 커버** — "데모와 운영 사이"의 이중 작업을 없앤다.
2. **비용 0 → 소액** — 학부 시연은 무료, 운영도 소형 VM 수준. Composer는 시연 규모엔 과한 고정비.
3. **한계가 명확** — 단일 호스트라는 제약이 또렷해(→ [12.5](#125-배포의-한계)) 멘토 피드백 *"컴포넌트 각각의 한계를 정의했는가"*([2026-06-02](../mentoring/2026-06-02-feedback.md))에 직접 답할 수 있다.

### 12.3 컨테이너 구성

공식 docker-compose를 **LocalExecutor 기준으로 단순화**한다(Celery용 redis·worker·flower 제거).

```
docker-compose.yaml
  ├─ postgres          ← Airflow metadata DB (run·task 상태·이력). 장독대 데이터 DB(Neon)와 별개
  ├─ airflow-init      ← DB 마이그레이션 + 관리자 계정 1회 생성 (다른 서비스의 선행 조건)
  ├─ airflow-apiserver ← Web UI·REST API (3.x에서 webserver 대체)
  ├─ airflow-scheduler ← 스케줄·의존성 판정 + LocalExecutor로 Task 실행
  └─ airflow-dag-processor ← dags/ 파싱·직렬화 (3.x 별도 서비스)
```

**Executor 선택** — 시연·소규모는 LocalExecutor가 정답이다.

| Executor | 실행 방식 | 추가 인프라 | 장독대 |
|----------|----------|------------|--------|
| **LocalExecutor** | 단일 머신의 프로세스 병렬 | 없음 | **채택** — 수집 2종 병렬이면 충분 |
| CeleryExecutor | 다중 워커 분산 | redis/rabbitmq + worker | 과함 (분산 불필요) |
| KubernetesExecutor | Task당 pod | K8s 클러스터 | 확장 시점에 재검토 |

**메타데이터 DB 분리** — Airflow의 상태 저장소(postgres 컨테이너)와 장독대 데이터 저장소(Neon)는 **완전히 별개**다(→ [0.3](#03-기본-아키텍처)). Task 코드는 Neon만 만지고, run·task 이력은 Airflow postgres에만 쌓인다. Airflow 3의 보안 모델(Task가 metadata DB 직접 접근 차단)과도 자연히 맞물린다.

**커스텀 이미지 — 코어 의존성만** — `apache/airflow` 베이스에 장독대 단계가 import하는 패키지를 설치한다. 단 **임베딩·클러스터링 코어가 실제로 쓰는 것만** 넣는다:

- **포함**: `langchain-google-vertexai`(gemini 임베딩), `hdbscan`·`scikit-learn`(`cluster.py`), `feedparser`·`httpx`·`finance-datareader`·`pykrx`·`trafilatura` 등 수집·전처리.
- **제외**: `sentence-transformers`·`langchain-huggingface`(torch ~2GB). HuggingFace 백엔드는 `embedding_client.py`의 **조건부 분기**라 gemini 운영 경로에선 import되지 않는다(평가 전용). 빼면 이미지가 수 GB 가벼워지고 빌드도 빨라진다.

> **의존성 격리 (중요)**: Airflow 3.0 코어는 SQLAlchemy **1.4**, 장독대 앱은 **2.0**(`DeclarativeBase` 등)이라 한 파이썬 환경에 못 섞는다. 앱 의존성을 이미지 안 **별도 venv**(`/home/airflow/jangdokdae-venv`)에 설치하고, DAG는 **`ExternalPythonOperator`**로 그 venv의 python을 호출한다 — 코어 환경(1.4)은 베이스 그대로 두고, 단계별 Task·관찰성을 유지하면서 충돌을 피한다. `hdbscan`은 네이티브 빌드라 이미지에 `gcc`/`g++`를 더한다.

**코드·비밀·시각** — 단계 코드(`app/`·`services/`·`utils/`·`prompts/`)와 `dags/`는 볼륨 마운트하고(Airflow 실행 로그는 `logs/` 볼륨으로 영속화), `PYTHONPATH`로 import 경로를 잡는다. 비밀은 **기존 `.env`를 `env_file`로 주입**하고 `vertex_key.json`은 read-only 마운트한다 — Airflow Connection/Hook을 쓰지 않아 접속 정보 관리를 이원화하지 않는다(→ [0.4](#04-핵심-개념)). 컨테이너 타임존은 KST로 맞춰 DAG cron(`Asia/Seoul`)과 DB의 KST naive 저장(→ [01](./01-pipeline-orchestration-design.md))을 일치시킨다.

### 12.4 운영 승격 경로

데모에서 운영으로 갈 때 **다시 만들지 않는다** — 올리는 위치만 바뀐다.

1. **CE VM 승격 (정본)**: 메모리 4GB+ Compute Engine 인스턴스(e2-medium 이상 권장)에 Docker 설치 → 같은 레포의 `docker-compose.yaml`을 그대로 `up`. 이미지·DAG·`.env`가 동일하므로 데모와 동작이 같다. 스케줄러가 KST cron으로 평일 09:00·15:30 자동 트리거.
2. **Composer 전환 (확장 시)**: 관리형이 필요해지면 **`dags/`만 Composer 버킷에 업로드**하고 의존성은 Composer 환경에 선언한다. DAG 코드는 단계 함수를 그대로 호출하므로 수정이 거의 없다 — 인프라가 추상화돼 있기 때문.

> 단계 간 데이터는 항상 공유 DB(Neon) 상태 핸드오프라(→ [6장](#6-전체-구조)), 실행 환경이 바뀌어도 단계 코드·핸드오프 규약은 불변이다. 이것이 "환경 교체만으로 승격"이 가능한 이유다.

### 12.5 배포의 한계 (전환 신호)

docker-compose 중심 선택의 **명시적 한계** — 이 선들을 넘으면 K8s/Composer로 전환한다.

| 한계 | 무슨 문제 | 전환 신호 |
|------|----------|----------|
| **단일 호스트 SPOF** | 호스트가 죽으면 스케줄러·DB·전부 정지 | 가용성 SLA가 필요해질 때 |
| **수동 재시작** | 컨테이너·VM 다운 시 자동 복구 없음 (systemd/`restart: always`로 완화하나 호스트 장애엔 무력) | 무중단 운영 요구 |
| **스케일아웃 불가** | LocalExecutor는 단일 머신 — Task가 늘면 수직 확장만 | 동시 Task가 VM 한 대를 초과 |
| **백필·대량 재처리 부담** | 큰 backfill을 단일 머신이 직렬 처리 | 과거 대량 재처리가 상시화 |

> 현재 워크로드(평일 2회, 수집 2종 병렬 + 임베딩)는 이 한계선 안에 충분히 들어온다. 한계를 "지금 막아야 할 결함"이 아니라 **"전환 시점을 알려주는 계기판"**으로 둔다.
