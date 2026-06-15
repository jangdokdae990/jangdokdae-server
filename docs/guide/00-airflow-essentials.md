# Airflow 핵심 개념 가이드

> **작성자** Kim minkyoung · **작성일** 2026-06-15
>
> **범위** Airflow를 처음 접하는 사람이 **개념 → 설치 → 배포**까지 익히는 범용 입문 학습 문서. 장독대 적용은 [00-workflow-airflow.md](../design/00-workflow-airflow.md)·[01-pipeline-orchestration-design.md](../design/01-pipeline-orchestration-design.md)을 본다.
>
> **읽는 법** 위에서부터 순서대로. 개념마다 일상 비유와 요약 표를 둔다. 코드는 "감을 잡는" 최소한만 싣는다.

---

## 목차

1. [왜 Airflow인가 — cron으로는 부족한 순간](#1-왜-airflow인가--cron으로는-부족한-순간)
2. [Workflow as Code — 워크플로우를 코드로 선언한다](#2-workflow-as-code--워크플로우를-코드로-선언한다)
3. [핵심 구성요소 — DAG·Task·의존성](#3-핵심-구성요소--dagtask의존성)
4. [실행 엔진 — 누가 언제 무엇을 돌리나](#4-실행-엔진--누가-언제-무엇을-돌리나)
5. [스케줄링 — 언제 돌릴지 정하기](#5-스케줄링--언제-돌릴지-정하기)
6. [실패와 재시도 — 멈춘 곳에서 다시](#6-실패와-재시도--멈춘-곳에서-다시)
7. [Task 간 통신 — XCom](#7-task-간-통신--xcom)
8. [관찰성 — Web UI에서 보는 것](#8-관찰성--web-ui에서-보는-것)
9. [아키텍처 한눈에](#9-아키텍처-한눈에)
10. [설치하기](#10-설치하기)
11. [배포 방식 개요](#11-배포-방식-개요)
12. [인증과 접근 제어 — 누가 Web UI에 들어오나](#12-인증과-접근-제어--누가-web-ui에-들어오나)
13. [더 알아보기](#13-더-알아보기)

---

## 1. 왜 Airflow인가 — cron으로는 부족한 순간

"매일 새벽 3시에 스크립트를 돌린다"가 전부라면 **cron으로 충분**하다. 문제는 작업이 **여러 단계로 이어지고, 서로 의존**하기 시작할 때 생긴다.

> 비유: 요리 한 접시(라면 끓이기)는 타이머 하나로 된다. 하지만 코스 요리(전채 → 메인 → 디저트, 일부는 동시에)를 타이머만으로 맞추려면 "전채가 끝났겠지" 하고 **시간을 추정**해야 한다. 추정이 빗나가면 재료가 준비되기 전에 다음 단계가 시작된다.

| cron의 한계 | 무슨 일이 생기나 | Airflow의 해법 |
|------|------|------|
| 의존성 표현 불가 | "수집이 끝나면 가공"을 시간 간격으로 추정 → 수집이 늦으면 빈 데이터로 가공 | `수집 >> 가공` — 선행이 **성공해야** 다음 실행 |
| 부분 실패 처리 부재 | 3단계 중 2단계가 죽으면 전체 재실행 | 실패한 단계만 **자동 재시도**, 성공분은 건너뜀 |
| 실행 이력 없음 | "어제 왜 비었지?"를 로그 grep으로 추적 | Web UI에서 회차별 성공/실패/소요시간 한눈에 |
| 과거 재처리 수동 | 3일치 빠지면 날짜 바꿔 수동 실행 | `backfill`로 기간 지정 일괄 재실행 |
| 알림 없음 | 실패를 다음 날 발견 | 실패 시 콜백·알림 내장 |

**한 줄 요약**: cron은 **"언제"**만 알고, Airflow는 **"언제 + 어떤 순서로 + 실패하면 어떻게"**까지 안다.

---

## 2. Workflow as Code — 워크플로우를 코드로 선언한다

Airflow의 철학은 **"Workflow as Code"** — 워크플로우를 GUI나 XML이 아니라 **파이썬 코드로 선언**한다.

코드로 선언하기 때문에:

- **버전 관리(git)** — 워크플로우 변경 이력이 코드 히스토리에 남는다.
- **코드 리뷰·테스트** — 일반 코드처럼 검토하고 테스트한다.
- **동적 생성** — 반복문으로 Task를 찍어내거나, 설정에 따라 그래프를 바꿀 수 있다.

```python
# "워크플로우 1개"를 파이썬 파일 하나로 선언한다 (개념 예시)
with DAG("my_pipeline", schedule="@daily", start_date=...) as dag:
    extract = PythonOperator(task_id="extract", python_callable=...)
    load    = PythonOperator(task_id="load",    python_callable=...)
    extract >> load          # 의존성: extract가 성공해야 load 실행
```

> 이 파이썬 파일을 **DAG 파일**이라 부르고, 정해진 폴더(`dags/`)에 두면 Airflow가 자동으로 읽어 들인다.

---

## 3. 핵심 구성요소 — DAG·Task·의존성

Airflow를 이해하는 첫 단어 네 개다.

| 용어 | 정의 | 비유 |
|------|------|------|
| **DAG** (Directed Acyclic Graph) | 워크플로우 1개 = Task들의 **방향 비순환 그래프** | 요리 **레시피** 전체 |
| **Task** | 실행 단위 1개 | 레시피의 **한 단계**("양파를 볶는다") |
| **Operator** | Task를 만드는 **템플릿** (PythonOperator, BashOperator…) | 단계에 쓰는 **도구**(칼·냄비) |
| **의존성** (`>>`) | Task 실행 순서 | "볶기 *다음에* 끓이기" |

**왜 "비순환(Acyclic)"인가?** 그래프에 순환(A→B→A)이 있으면 영원히 끝나지 않는다. 순환을 금지해야 **"언젠가 반드시 끝남"**이 보장된다.

```python
a >> b >> c        # a 다음 b 다음 c (직렬)
a >> [b, c]        # a 다음에 b와 c를 병렬로
[b, c] >> d        # b와 c가 모두 끝나면 d
```

**한 번 더 — 회차 개념**: DAG와 Task는 "설계도"이고, 실제로 돌 때마다 생기는 "실행 인스턴스"는 따로 부른다.

| 설계도 | 실행 인스턴스 (특정 회차) |
|------|------|
| **DAG** | **DAG Run** — DAG의 실행 1회 (스케줄/수동 트리거) |
| **Task** | **Task Instance** — 특정 회차에서의 Task 실행 1회 (성공/실패/재시도 상태를 가짐) |

> 예: "10월 5일 09:00 run"이 DAG Run 하나, 그 안의 "extract Task 실행"이 Task Instance 하나.

---

## 4. 실행 엔진 — 누가 언제 무엇을 돌리나

DAG를 작성했다고 저절로 돌지 않는다. 뒤에서 여러 **서비스**가 협력한다.

| 컴포넌트 | 역할 | 비유 |
|------|------|------|
| **Scheduler** | "지금 실행할 때가 된 Task"를 판정. Airflow의 **심장** | 주방장 — 무엇을 시작할지 지시 |
| **Executor** | Task를 **어떻게/어디서** 실행할지 결정 | 인력 배치 방식 |
| **Worker** | Task를 **실제로** 실행하는 일꾼 | 요리사 |
| **DAG Processor** | `dags/` 폴더의 파이썬 파일을 주기적으로 파싱 | 레시피북을 읽어 등록 |
| **Metadata DB** | 모든 상태(run·task·스케줄·이력)의 **단일 출처** | 주방 화이트보드 |
| **API Server** | Web UI·REST API 제공 | 손님 응대 창구 |

**Executor가 헷갈리기 쉽다** — "어떻게 일꾼을 굴리는가"의 선택지다.

| Executor | 실행 방식 | 추가 인프라 | 언제 |
|----------|----------|------------|------|
| **LocalExecutor** | 단일 머신의 여러 프로세스로 병렬 | 없음 | 소규모·단일 서버·학습 |
| **CeleryExecutor** | 여러 워커에 분산 | 메시지 브로커(redis 등) + 워커 | 중규모 분산 |
| **KubernetesExecutor** | Task마다 K8s pod 생성 | 쿠버네티스 클러스터 | 대규모·격리 필요 |

> 처음 배울 땐 **LocalExecutor 하나만** 알면 된다. 나머지는 "규모가 커지면 갈아끼우는 옵션"이다.

---

## 5. 스케줄링 — 언제 돌릴지 정하기

| 개념 | 뜻 |
|------|------|
| **schedule** | 얼마나 자주 도는가. cron 표현식(`0 9 * * 1-5` = 평일 09:00)이나 프리셋(`@daily`) |
| **start_date** | 스케줄이 시작되는 기준 시점 |
| **catchup** | 과거 미실행 구간을 **소급 실행**할지. `False`면 안 함 |
| **backfill** | 지정한 **과거 기간**의 run을 일괄 (재)실행하는 명령 |
| **timetable** | cron만으로 표현 못 하는 복잡한 일정(예: 하루 두 번 다른 시각)을 다루는 객체 |

**cron 표현식 빠른 해독** — `분 시 일 월 요일`

```
0 9 * * 1-5   → 매 평일(월~금) 09시 00분
30 15 * * *   → 매일 15시 30분
0 0 1 * *     → 매월 1일 00시
```

**catchup이 함정이다.** `start_date`를 과거로 두고 `catchup=True`(기본값이었던 시절)면, 켜는 순간 그동안 안 돈 모든 구간을 **한꺼번에 소급 실행**한다. 의도치 않으면 `catchup=False`로 둔다.

> **data interval**: Airflow는 각 run에 "이 run이 책임지는 시간 구간"을 부여한다. 일배치라면 "어제 0시~오늘 0시" 같은 식. 데이터 파이프라인에서 "어느 구간을 처리하는 run인가"를 분명히 해 멱등성·backfill을 가능하게 한다.

---

## 6. 실패와 재시도 — 멈춘 곳에서 다시

외부 API는 가끔 실패한다. Airflow는 이를 **선언적으로** 다룬다.

```python
default_args = {
    "retries": 2,                       # 실패 시 최대 2번 더 시도
    "retry_delay": timedelta(seconds=60),  # 1분 간격
}
```

**핵심 마인드셋 — "원복이 아니라 재개"**

- 잘 설계된 파이프라인의 각 단계는 **"아직 처리 안 된 것만"** 집어간다(예: "임베딩이 비어 있는 행만").
- 그래서 중간에 실패하고 다시 돌려도, 이미 끝난 일을 되돌리지 않고 **남은 일만** 이어서 한다.
- 이를 위해 각 Task는 **멱등(idempotent)**해야 한다 — 같은 입력으로 여러 번 돌려도 결과가 같아야 재시도가 안전하다.

> 재시도가 안전하려면 멱등성이 전제다. "두 번 저장해도 중복이 안 생기게"(예: `ON CONFLICT DO NOTHING`) 만들어 두는 게 흔한 패턴이다.

---

## 7. Task 간 통신 — XCom

Task는 서로 독립 프로세스라 변수를 직접 넘길 수 없다. **XCom**(cross-communication)은 Task 사이에 **소량 데이터**를 주고받는 우편함이다.

> 비유: 요리사끼리 직접 대화하는 대신 **포스트잇 쪽지**를 화이트보드(Metadata DB)에 붙인다.

- **적합**: 카운트, 작은 ID 목록, 신호 값 같은 **작은** 데이터.
- **부적합**: 대용량(데이터프레임·파일). XCom은 Metadata DB를 거치므로 큰 데이터를 넣으면 DB가 비대해진다.

**실무 패턴**: 큰 데이터는 **공유 저장소(DB·객체스토리지)**에 두고, XCom에는 "어디에 뒀는지"나 "몇 건 처리했는지"만 흘린다.

---

## 8. 관찰성 — Web UI에서 보는 것

Airflow의 큰 가치 중 하나는 **무슨 일이 있었는지 한눈에 보이는 것**이다. Web UI(API Server 제공)에서:

- **Grid 뷰**: 회차×Task 격자. 초록(성공)·빨강(실패)·노랑(재시도)이 한눈에.
- **Graph 뷰**: DAG의 의존성 그래프와 각 Task 상태.
- **로그**: Task Instance별 실행 로그를 클릭 한 번에.
- **소요 시간**: 어느 Task가 느려지는지 추세로.

> cron이라면 "왜 비었지?"를 서버 로그 grep으로 찾아야 하지만, Airflow는 **클릭 몇 번**으로 도달한다. 이것이 *observability*다.

---

## 9. 아키텍처 한눈에

지금까지의 컴포넌트가 어떻게 맞물리는지 그림으로 정리한다.

```
                    ┌──────────────┐
   DAG 파일(dags/) → │ DAG Processor │ ─ 파싱·등록 ─┐
                    └──────────────┘              ▼
                    ┌──────────────┐       ┌─────────────┐
        사용자 ←──── │  API Server  │ ←───→ │ Metadata DB │ ← 모든 상태의 단일 출처
       (Web UI)     └──────────────┘       │ (PostgreSQL) │  (run·task 상태·이력)
                    ┌──────────────┐       └─────────────┘
                    │  Scheduler   │ ─ "실행할 Task" 판정 → Executor → ┌────────┐
                    └──────────────┘                                 │ Worker │ ← 실제 실행
                                                                     └────────┘
```

**한 줄 흐름**: DAG Processor가 레시피를 등록 → Scheduler가 "이제 시작" 판정 → Executor가 Worker에 배치 → Worker가 실행 → 모든 상태는 Metadata DB에 기록 → 사람은 API Server(Web UI)로 들여다본다.

---

## 10. 설치하기

처음 띄워보는 방법을 쉬운 순서로 셋 소개한다.

### 10.1 가장 빠른 맛보기 — `airflow standalone`

단일 명령으로 모든 컴포넌트(스케줄러·API 서버·DB 초기화)를 한 번에 띄운다. **학습·실험 전용**이다.

```bash
pip install "apache-airflow==3.0.0" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-3.0.0/constraints-3.12.txt"
export AIRFLOW_HOME=~/airflow
airflow standalone        # http://localhost:8080 (콘솔에 admin 비밀번호 출력)
```

> **constraint 파일**이 중요하다. Airflow는 의존성이 많아, 공식이 검증한 버전 조합(constraints-<버전>-<파이썬>.txt)을 함께 지정해야 설치 충돌을 피한다.

### 10.2 컨테이너로 — 공식 이미지

```bash
docker pull apache/airflow:3.0.0
```

격리된 환경에서 동일하게 재현된다. 추가 파이썬 패키지가 필요하면 이 이미지를 베이스로 **커스텀 Dockerfile**을 만든다(Docker 자체 개념은 → [01-docker-essentials](01-docker-essentials.md)).

```dockerfile
FROM apache/airflow:3.0.0
# 베이스의 apache-airflow 버전을 그대로 고정해 충돌 방지
ADD requirements.txt .
RUN pip install apache-airflow==3.0.0 -r requirements.txt
```

### 10.3 여러 서비스 한 번에 — 공식 docker-compose

스케줄러·API 서버·DAG 프로세서·메타데이터 DB를 **함께** 띄우는 가장 흔한 로컬 구성이다.

```bash
curl -LfO "https://airflow.apache.org/docs/apache-airflow/stable/docker-compose.yaml"
mkdir -p dags logs plugins config
docker compose up airflow-init    # DB 초기화·관리자 계정 생성(최초 1회)
docker compose up                 # 전체 기동 → http://localhost:8080
```

> 공식 docker-compose는 **학습·로컬 개발용**으로 명시돼 있다(프로덕션 아님). 프로덕션 배포는 다음 장에서.

---

## 11. 배포 방식 개요

Airflow는 어디서 돌리든 **컨테이너 기반**이라는 점은 같고, **그 컨테이너를 누가·어디서 관리하느냐**가 갈린다.

| 방식 | 비용 | 운영 복잡도 | 적합 규모 | 표준성 |
|------|------|------------|----------|--------|
| **로컬 docker-compose** | 0 | 낮음 | 학습·데모 | 공식 제공(비프로덕션) |
| **VM + docker-compose** | 소형 VM 소액 | 중 (직접 관리) | 소규모 운영 | 간이 운영 |
| **Kubernetes + 공식 Helm chart** | 클러스터+공수 | 높음 | 중·대규모 | 자체 호스팅 **프로덕션 표준** |
| **관리형** (Cloud Composer·AWS MWAA·Astronomer) | 월 고정비 | 낮음(위탁) | 본격 운영 | 관리형 **프로덕션 표준** |

**고르는 기준**

- **배우는 중·데모** → 로컬 docker-compose. 무료이고 공식이 제공한다.
- **작게 운영** → VM 한 대에 같은 docker-compose. 데모 자산을 그대로 승격할 수 있다.
- **규모·안정성 요구** → K8s+Helm(직접) 또는 관리형(위탁). DAG 코드는 그대로 두고 실행 환경만 바꾼다.

> **핵심**: DAG·Task 코드는 실행 환경과 분리돼 있어, 처음엔 로컬 compose로 시작했다가 나중에 K8s/관리형으로 **환경만 교체**하며 승격할 수 있다.

장독대가 이 중 무엇을 어떤 근거로 골랐는지(docker-compose 중심 + Compute Engine 승격 경로)는 → [00-workflow-airflow.md §12 배포·실행 환경](../design/00-workflow-airflow.md#12-배포실행-환경).

---

## 12. 인증과 접근 제어 — 누가 Web UI에 들어오나

DAG를 띄우면 Web UI(§8)가 열린다. 누구나 들어와 파이프라인을 돌리고 멈출 수 있으면 곤란하므로, Airflow는 **로그인**으로 접근을 막는다. 이 로그인을 담당하는 부품이 **Auth Manager**다.

> 비유: Auth Manager는 건물 **출입 통제 시스템**이다. 작은 사무실은 "문 앞 비밀번호 자물쇠" 하나로 충분하지만, 큰 회사는 "사원증 + 부서별 권한"이 필요하다. 규모에 맞춰 통제 방식을 갈아끼운다.

### 12.1 Auth Manager — 인증을 갈아끼우는 추상화

Airflow 3.0은 인증을 **Auth Manager**라는 교체 가능한 부품으로 분리했다. 실행 환경처럼(§4 Executor), 규모가 커지면 부품만 바꾼다.

| Auth Manager | 인증 방식 | 언제 |
|------|------|------|
| **SimpleAuthManager** (기본) | 사용자·비밀번호를 파일로 관리 | 학습·데모·소규모 |
| **FabAuthManager** | DB 기반 사용자·역할·세분 권한(RBAC) | 본격 운영 |
| **외부 IdP 연동** | OAuth·LDAP·SSO 등 사내 인증 위임 | 조직 표준 인증 |

### 12.2 SimpleAuthManager — 비밀번호가 "파일에만" 산다

기본값인 SimpleAuthManager는 단순하다. **누가 무슨 역할인지**는 설정으로 정하고(`admin`은 전체 권한, `viewer`는 읽기 전용), **비밀번호**는 처음 기동할 때 **자동 생성**해 파일 한 곳에 적어둔다.

| 항목 | 어디에 | 핵심 |
|------|------|------|
| 사용자·역할 | 설정값 (`simple_auth_manager_users`) | `admin:admin,bob:viewer` 형식 |
| 비밀번호 | `$AIRFLOW_HOME/simple_auth_manager_passwords.json.generated` | 첫 기동 시 **랜덤 자동 생성** |

**꼭 알아야 할 제약**: SimpleAuthManager는 비밀번호를 **오직 이 JSON 파일에서만** 읽는다. "환경변수로 비밀번호를 직접 주입하는" 옵션이 **없다**. 그래서 비밀번호를 내 마음대로 정하려면, **그 파일을 원하는 값으로 만들어 두는 수밖에 없다**.

> 처음 띄울 때 콘솔이나 이 파일에서 admin 비밀번호를 확인해 로그인한다(`airflow standalone`도 동일). 파일이 이미 있으면 그 값을 그대로 쓰고, 없으면 새로 랜덤 생성한다.

### 12.3 비밀번호를 다루는 두 가지 방식

비밀번호 파일을 어떻게 만들어 두느냐에 따라 임시/관리형으로 갈린다.

| 방식 | 하는 일 | 한계 / 쓰임 |
|------|--------|------------|
| **임시 변경** | 실행 중 컨테이너의 비번 파일을 직접 수정 후 재시작 | 컨테이너를 **재생성하면 사라짐**. 빠른 확인용 |
| **설정으로 관리** | `.env`에 둔 값으로 **기동 시 파일을 생성** | 재생성에도 유지·IaC로 관리. 시크릿을 `.env` 한곳에 일원화 |

**관리형의 핵심 아이디어**: 비밀번호 값은 다른 시크릿(DB·API 키)과 똑같이 `.env`에 두고, 컨테이너가 **뜰 때** 그 값으로 파일을 만들어 정규 기동으로 넘긴다. 코드·이미지에는 비밀번호가 박히지 않는다(전역 규칙: 시크릿 하드코딩 금지).

### 12.4 알아두면 좋은 컨테이너 개념 — `$$`와 entrypoint

위 "기동 시 파일 생성"을 docker-compose로 구현할 때 만나는 두 개념이다.

- **entrypoint 가로채기**: 컨테이너가 본래 명령을 실행하기 **직전에** 짧은 준비 스크립트(비번 파일 생성)를 끼워 넣고, 끝에 원래 진입점으로 넘긴다(`exec`).
- **`$$`(달러 두 개)**: docker-compose 파일에서 `$VAR`는 compose가 **미리 치환**해 평문이 파일·로그에 박힐 수 있다. `$$VAR`로 쓰면 치환을 미뤄 **컨테이너 안에서 실행될 때** 값이 풀린다 → 비밀번호가 yaml·빌드 로그에 노출되지 않는다.

> 한 줄 요약: 비밀번호처럼 민감한 값은 compose가 아니라 **컨테이너 런타임**에서 풀리게(`$$`) 해, 흔적을 남기지 않는다.

### 12.5 운영으로 갈 때

SimpleAuthManager는 이름처럼 **간이용**이다. 사용자가 늘고 권한을 세분화(부서별 읽기/실행 구분)해야 하거나, 사내 SSO에 묶어야 하면 **FabAuthManager나 외부 IdP 연동**으로 부품을 교체한다 — DAG 코드는 그대로 두고 인증 계층만 바꾼다(§4 Executor 교체와 같은 원리).

장독대가 데모 단계에서 SimpleAuthManager + `.env` 관리 방식을 택한 근거와 운영 전환 방침은 → [00-workflow-airflow.md §12.3](../design/00-workflow-airflow.md#12-배포실행-환경).

---

## 13. 더 알아보기

**공식 문서**

- [Airflow 공식 문서](https://airflow.apache.org/docs/)
- [Core Concepts (개념 총람)](https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/index.html)
- [Docker Compose로 실행하기](https://airflow.apache.org/docs/apache-airflow/stable/howto/docker-compose/index.html)

**장독대 적용**

- [00-workflow-airflow.md — 워크플로우 오케스트레이션(Airflow vs LangGraph 배치·배포)](../design/00-workflow-airflow.md)
- [01-pipeline-orchestration-design.md — 파이프라인 오케스트레이션(단계 간 데이터 핸드오프)](../design/01-pipeline-orchestration-design.md)
