# Docker 핵심 개념 가이드

> **작성자** Kim minkyoung · **작성일** 2026-06-15
>
> **범위** Airflow를 Docker로 띄우며 만나는 **Docker·docker-compose 핵심 개념**을 처음 접하는 사람이 익히는 입문 학습 문서. 장독대 적용은 [00-workflow-airflow.md §11·§12](../design/00-workflow-airflow.md#12-배포실행-환경)와 실제 `Dockerfile`·`docker-compose.yaml`을 본다.
>
> **읽는 법** 위에서부터 순서대로. 개념마다 일상 비유와 요약 표를 둔다. 코드는 "감을 잡는" 최소한만 싣는다. Airflow 자체 개념은 [00-airflow-essentials](00-airflow-essentials.md)를 먼저 본다.

---

## 목차

1. [왜 Docker인가 — "내 컴퓨터에선 됐는데"](#1-왜-docker인가--내-컴퓨터에선-됐는데)
2. [이미지와 컨테이너 — 붕어빵 틀과 붕어빵](#2-이미지와-컨테이너--붕어빵-틀과-붕어빵)
3. [Dockerfile — 이미지를 코드로 굽는다](#3-dockerfile--이미지를-코드로-굽는다)
4. [빌드 캐시와 레이어 — 순서가 속도를 가른다](#4-빌드-캐시와-레이어--순서가-속도를-가른다)
5. [빌드 컨텍스트와 .dockerignore](#5-빌드-컨텍스트와-dockerignore)
6. [여러 컨테이너 한 번에 — docker-compose](#6-여러-컨테이너-한-번에--docker-compose)
7. [데이터는 어디에 — 볼륨](#7-데이터는-어디에--볼륨)
8. [설정과 비밀 주입 — 환경변수](#8-설정과-비밀-주입--환경변수)
9. [entrypoint와 command — 컨테이너가 뜰 때 무엇을 하나](#9-entrypoint와-command--컨테이너가-뜰-때-무엇을-하나)
10. [네트워크 — 컨테이너끼리 이름으로 대화](#10-네트워크--컨테이너끼리-이름으로-대화)
11. [의존성 충돌을 가르는 법 — venv 격리](#11-의존성-충돌을-가르는-법--venv-격리)
12. [로컬 런타임 — Docker Desktop과 colima](#12-로컬-런타임--docker-desktop과-colima)
13. [더 알아보기](#13-더-알아보기)

---

## 1. 왜 Docker인가 — "내 컴퓨터에선 됐는데"

같은 코드인데 내 노트북에선 돌고 동료 PC나 서버에선 안 돈다. 파이썬 버전·OS 라이브러리·환경변수가 미묘하게 다르기 때문이다. **Docker는 "앱 + 그 앱이 필요로 하는 환경 전체"를 통째로 묶어** 어디서나 똑같이 돌게 한다.

> 비유: 화물 **컨테이너**. 안에 무엇을 싣든 규격이 같아, 배·트럭·기차 어디에 올려도 똑같이 다뤄진다. 운송 수단(내 PC·서버·클라우드)이 내용물을 신경 쓸 필요가 없다.

| Docker 없이 | 무슨 일이 생기나 | Docker의 해법 |
|------|------|------|
| 환경 수동 세팅 | "파이썬 3.12 깔고, 이 라이브러리 깔고…"를 머신마다 반복 | 이미지 하나로 **동일 환경 재현** |
| 버전 충돌 | A앱은 라이브러리 1.4, B앱은 2.0 필요 → 한 머신에 공존 곤란 | 앱마다 **격리된 컨테이너** |
| "내 PC에선 됐는데" | 배포 환경과 개발 환경 차이로 장애 | 개발·운영이 **같은 이미지** |

---

## 2. 이미지와 컨테이너 — 붕어빵 틀과 붕어빵

Docker에서 가장 먼저 구분할 두 단어다.

| 용어 | 정의 | 비유 |
|------|------|------|
| **이미지(Image)** | 앱 + 환경을 담은 **읽기 전용 템플릿** | 붕어빵 **틀** |
| **컨테이너(Container)** | 이미지를 실행한 **인스턴스** | 틀로 찍어낸 **붕어빵** |

- 이미지 하나로 컨테이너를 **여러 개** 찍어낼 수 있다(같은 틀 → 붕어빵 여러 개).
- 컨테이너는 쓰고 버리는 것(ephemeral) — 멈추고 지워도 이미지는 그대로다.
- 그래서 **컨테이너 안에서 만든 데이터는 컨테이너를 지우면 사라진다** → 영속이 필요하면 볼륨(§7)을 쓴다.

> 장독대 예: `apache/airflow:3.0.0` 베이스 이미지로 커스텀 이미지를 굽고, 그 이미지에서 `airflow-apiserver`·`scheduler`·`dag-processor` **컨테이너 여러 개**를 띄운다(같은 이미지, 다른 역할).

---

## 3. Dockerfile — 이미지를 코드로 굽는다

이미지를 손으로 만들지 않고 **레시피 파일(`Dockerfile`)**로 선언한다. Airflow의 "Workflow as Code"처럼, 환경을 **코드로** 관리하는 셈이다.

```dockerfile
FROM apache/airflow:3.0.0-python3.12   # ① 베이스 이미지에서 출발
USER root
RUN apt-get install -y gcc g++          # ② OS 패키지 설치
USER airflow
COPY requirements-airflow.txt /req.txt  # ③ 파일 복사
RUN pip install -r /req.txt             # ④ 파이썬 의존성 설치
```

| 명령 | 하는 일 |
|------|------|
| **FROM** | 출발점이 되는 베이스 이미지 |
| **RUN** | 빌드 중 명령 실행(패키지 설치 등) |
| **COPY** | 호스트 파일을 이미지 안으로 복사 |
| **USER** | 이후 명령을 실행할 사용자 전환 |

> 핵심: 베이스 이미지의 **버전을 그대로 고정**해 충돌을 피한다(Airflow는 의존성이 많아 특히 중요). 장독대 `Dockerfile`은 베이스 그대로 두고, 앱 의존성만 별도 venv에 따로 깐다(§11).

---

## 4. 빌드 캐시와 레이어 — 순서가 속도를 가른다

Dockerfile의 **각 명령(FROM·RUN·COPY…)은 "레이어" 하나**를 만든다. Docker는 레이어를 **캐시**해, 바뀌지 않은 레이어는 다시 빌드하지 않는다.

> 비유: 레이어는 **케이크 층**. 위층(나중 명령)만 바꿀 땐 아래층을 다시 굽지 않는다. 하지만 아래층을 건드리면 그 위 전부를 다시 구워야 한다.

**규칙: 자주 바뀌는 것을 뒤에 둔다.** 코드는 자주 바뀌고 OS 패키지·의존성 목록은 드물게 바뀐다. 그래서:

```dockerfile
COPY requirements.txt .   # 의존성 목록(드물게 변경) — 먼저
RUN pip install -r requirements.txt
COPY . .                  # 앱 코드(자주 변경) — 나중
```

이렇게 두면 코드만 고쳤을 때 무거운 `pip install` 레이어가 **캐시에서 재사용**돼 빌드가 빨라진다. 반대로 두면 코드 한 줄만 바꿔도 매번 전체 재설치한다.

---

## 5. 빌드 컨텍스트와 .dockerignore

`docker build`를 하면 현재 폴더(빌드 컨텍스트) 전체가 빌드 엔진으로 **전송**된다. 불필요한 파일(가상환경·로그·`.git`)까지 보내면 느리고, **비밀 파일이 이미지에 섞여 들어갈** 위험도 있다.

`.dockerignore`는 git의 `.gitignore`처럼 **빌드에서 제외할 것**을 적는다.

```
.env                # 비밀 — 이미지에 굽지 않는다
app/credentials/    # 키 파일
.venv/  __pycache__/  .git/  logs/
```

> 원칙: **비밀(.env·키)은 이미지에 굽지 않고, 실행할 때 주입**한다(§8). 이미지는 어디로든 복사·공유될 수 있어, 비밀이 박히면 유출 경로가 된다.

---

## 6. 여러 컨테이너 한 번에 — docker-compose

실제 앱은 컨테이너 하나로 안 끝난다. Airflow만 해도 API 서버·스케줄러·DAG 프로세서·메타데이터 DB가 **함께** 떠야 한다. 이를 일일이 `docker run` 하는 대신, **`docker-compose.yaml` 한 파일에 여러 컨테이너(서비스)를 선언**해 한 번에 띄운다.

```bash
docker compose up      # 선언한 서비스 전부 기동
docker compose down    # 전부 정리
```

| 개념 | 뜻 |
|------|------|
| **service** | compose가 관리하는 컨테이너 1종(예: `postgres`, `airflow-apiserver`) |
| **depends_on** | 기동 순서 의존성("DB가 뜬 다음 앱") |
| **healthcheck** | "정말 준비됐는지" 확인(포트 떴다고 DB 준비된 건 아님) |
| **anchor(`&`/`*`)** | YAML에서 공통 설정을 한 번 정의해 여러 서비스가 **재사용** |

> 장독대 예: `postgres`(Airflow 메타데이터 DB) + `airflow-init`(DB 마이그레이션 1회) + `apiserver`·`scheduler`·`dag-processor`를 한 compose에 묶고, 공통 환경·볼륨은 `x-airflow-common` anchor로 한 번만 적는다. ⚠️ 이 postgres는 **Airflow 운영용**이고, 장독대 데이터는 별도 Neon DB다.

---

## 7. 데이터는 어디에 — 볼륨

컨테이너를 지우면 그 안의 데이터는 사라진다(§2). 살아남아야 하는 데이터, 혹은 호스트와 공유할 파일은 **볼륨(volume)**으로 컨테이너 **밖**에 둔다.

| 종류 | 형태 | 쓰임 |
|------|------|------|
| **bind mount** | 호스트의 특정 폴더를 컨테이너에 연결 | 개발 중 **코드 실시간 반영**(고치면 즉시 컨테이너에 보임) |
| **named volume** | Docker가 관리하는 영속 저장소 | **DB 데이터**처럼 오래 보존할 것 |

```yaml
volumes:
  - ./dags:/opt/jangdokdae/dags        # bind: 코드를 컨테이너에 연결
  - airflow-db-volume:/var/lib/postgresql/data   # named: DB 영속
```

> 장독대 예: `dags`·`app`·`services` 등 코드는 **bind mount**라 고치면 재빌드 없이 반영되고, postgres 데이터는 **named volume**이라 `down`해도 보존된다. 반대로, 마운트하지 않은 컨테이너 내부 파일(예: 자동 생성 비번 파일)은 재생성 시 사라진다 → [00 §12.3 인증](00-airflow-essentials.md#12-인증과-접근-제어--누가-web-ui에-들어오나) 참고.

---

## 8. 설정과 비밀 주입 — 환경변수

이미지는 고정이지만, 같은 이미지를 **환경마다 다르게** 돌려야 한다(개발 DB vs 운영 DB). 그 차이를 **환경변수**로 바깥에서 주입한다. 비밀(DB·API 키·비밀번호)도 이미지에 굽지 않고 여기로 넣는다(§5).

| 방법 | 뜻 |
|------|------|
| **environment** | compose 파일에 직접 키·값을 적음(비밀 아님에 적합) |
| **env_file** | `.env` 파일을 통째로 컨테이너 환경으로 주입(비밀 일원화) |

**`$`와 `$$`의 차이 (헷갈리기 쉬움)**: docker-compose 파일에서

- `${VAR}` → compose가 **빌드 시 미리 치환**. 값이 최종 설정·로그에 박힐 수 있다.
- `$$VAR` → 치환을 미뤄 **컨테이너 런타임에** 값이 풀린다. 비밀이 yaml·로그에 노출되지 않는다.

> 장독대 예: `env_file: .env`로 Neon `DATABASE_URL`·Vertex 키 경로 등을 주입하고, admin 비밀번호는 `$$AIRFLOW_ADMIN_PASSWORD`로 **런타임에** 풀어 흔적을 남기지 않는다([00 §12.4](00-airflow-essentials.md#12-인증과-접근-제어--누가-web-ui에-들어오나)).

---

## 9. entrypoint와 command — 컨테이너가 뜰 때 무엇을 하나

컨테이너가 시작될 때 실행하는 것을 두 가지로 나눠 정한다.

| 항목 | 뜻 | 비유 |
|------|------|------|
| **entrypoint** | 항상 실행되는 **고정 진입점** | 가게의 "개점 준비 절차" |
| **command** | 진입점에 넘기는 **인자**(바꾸기 쉬움) | 그날 "무엇을 팔지" |

**가로채기 패턴**: 본래 진입점 앞에 짧은 준비 스크립트를 끼워 넣고, 끝에서 `exec`로 원래 진입점에 넘긴다.

```bash
echo "{...}" > 비번파일       # 준비 작업
exec /entrypoint api-server   # 원래 하던 일로 넘김
```

> 장독대 예: apiserver가 본래 `api-server`를 돌리기 **직전에** `.env` 값으로 비밀번호 파일을 만들고 정규 진입점으로 넘긴다. SimpleAuthManager가 비번을 파일에서만 읽는 제약을 이 패턴으로 우회한다(§8·00 §12).

---

## 10. 네트워크 — 컨테이너끼리 이름으로 대화

compose로 띄운 서비스들은 **자동으로 같은 네트워크**에 들어가, 서로를 **서비스 이름**으로 부른다. IP를 몰라도 된다.

```
postgresql+psycopg2://airflow:airflow@postgres/airflow
                                      ▲
                          서비스 이름이 곧 호스트명
```

> 비유: 같은 사무실(네트워크) 안에선 "회계팀!"(서비스 이름)이라고 부르면 통한다. 외부에서 들어오려면 정문(포트 매핑)이 필요하다.

**포트 매핑**: 컨테이너 안의 포트를 호스트로 열어 외부에서 접근하게 한다. `8080:8080`은 "호스트 8080 → 컨테이너 8080".

> 장독대 예: 앱 컨테이너가 메타데이터 DB를 `@postgres`(서비스 이름)로 찾고, Web UI는 `ports: 8080:8080`으로 호스트에 열려 브라우저에서 `localhost:8080`으로 접속한다.

---

## 11. 의존성 충돌을 가르는 법 — venv 격리

한 이미지 안에서 **서로 못 섞이는 의존성**을 함께 써야 할 때가 있다. 장독대가 정확히 그랬다.

| 쪽 | 요구 | 충돌 |
|------|------|------|
| Airflow 코어 | SQLAlchemy **1.4** | 한 환경에 |
| 장독대 앱 | SQLAlchemy **2.0** | 동시 설치 불가 |

**해법**: 한 이미지 안에 **별도의 가상환경(venv)을 하나 더** 만들어 앱 의존성(2.0)을 격리하고, Airflow는 베이스 환경(1.4)을 그대로 쓴다. 그리고 앱 코드는 그 venv의 파이썬으로 실행한다.

> 비유: 한 건물(이미지) 안에 **방음 부스(venv)**를 따로 둬, 서로 다른 음악(버전)이 간섭하지 않게 한다.

> 장독대 예: `Dockerfile`이 `/home/airflow/jangdokdae-venv`에 앱 의존성을 깔고, DAG는 `ExternalPythonOperator`로 이 venv의 파이썬을 호출한다. 단, 그 venv에서 도는 코드는 베이스 환경의 모듈을 못 보므로 **self-contained**(필요한 import를 함수 안에서)로 작성해야 한다(00-workflow-airflow.md §12.3).

---

## 12. 로컬 런타임 — Docker Desktop과 colima

`docker` 명령을 쓰려면 백그라운드에서 컨테이너를 돌리는 **엔진**이 있어야 한다. macOS·Windows는 리눅스가 아니라, 내부적으로 경량 리눅스 VM 위에서 엔진이 돈다.

| 런타임 | 형태 | 특징 |
|------|------|------|
| **Docker Desktop** | GUI 앱 | 가장 흔함. 일정 규모 이상 조직은 유료 |
| **colima** | CLI 도구(macOS) | 가볍고 무료, 터미널 중심 |

```bash
colima start          # 엔진 시작(VM 기동)
docker compose up     # 이후 docker 명령은 동일
```

> `docker`/`docker compose` 명령 자체는 어느 런타임이든 똑같다. 엔진만 갈아끼우는 것이라, 학습 내용은 그대로 통한다. 장독대 로컬 개발은 colima를 쓴다.

---

## 13. 더 알아보기

**공식 문서**

- [Docker 공식 문서](https://docs.docker.com/)
- [Dockerfile 작성 모범 사례](https://docs.docker.com/build/building/best-practices/)
- [Compose 파일 레퍼런스](https://docs.docker.com/reference/compose-file/)

**장독대 적용**

- [00-workflow-airflow.md §11·§12 — 디렉토리 구조·배포·실행 환경](../design/00-workflow-airflow.md#12-배포실행-환경)
- [00-airflow-essentials — Airflow 핵심 개념(설치·배포·인증 포함)](00-airflow-essentials.md)
- 실제 구성 파일: 루트의 `Dockerfile`·`docker-compose.yaml`·`.dockerignore`·`requirements-airflow.txt`
