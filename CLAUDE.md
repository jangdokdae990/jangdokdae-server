# 심화 프로젝트

- 프로젝트명: 장독대
- 프로젝트 뜻: 시장 독해를 대신 해드립니다를 줄여서 장독대
- 주린이(주식 초보자)를 위한 주식 시장 독해 보조 웹 서비스 — 시장·뉴스를 쉽게 풀어주고 스스로 판단하도록 돕는다(큐레이션·학습 포함)
- 타깃(정밀화): 2030 · 투자 경력 2년 미만 · 경제 용어 절반 이하 이해 · 뉴스·공시를 못 읽어 2차 가공물 의존

## 기술 스택

- 백엔드: python 3.12, fastapi
- db: neon, postgresql, pgvector
- 인증: 카카오, 구글 oauth 2.0
- llm: vertex ai - gemini, langchain 1.x, langgraph 1.x, langchain-google-vertexai 3.x
- 패키지 관리: uv

## 빠른 시작

```bash
cp .env.example .env           # 환경 변수 설정
uv sync                        # 의존성 설치
uvicorn app.main:app --reload  # 개발 서버 (http://localhost:8000)
```

API 문서: <http://localhost:8000/docs>

### 파이프라인 실행

```bash
# 로컬 1회 완주 (수집→임베딩·클러스터링→분석) — 테스트용, 부분 실패 시 전체 중단
python -m services.pipeline.runner

# 운영: Airflow가 Task별 격리·재시도 담당 (docker-compose)
docker compose up -d        # Airflow(웹서버/스케줄러/DAG 프로세서) 기동
```

## 테스트

```bash
pytest                # 전체 테스트
pytest --cov=app      # 커버리지 포함
```

## 참고 문서

- [`docs/rules/architecture.md`](docs/rules/architecture.md) — 폴더 구조 및 레이어 설명
- [`docs/rules/conventions.md`](docs/rules/conventions.md) — 파일명/클래스명/함수명 규칙
- [`.env.example`](.env.example) — 필요한 환경 변수 목록
- [`docs/design/00-workflow-airflow.md`](docs/design/00-workflow-airflow.md) — Airflow 오케스트레이션 설계(venv 격리 등)
- [`docs/guide/00-airflow-essentials.md`](docs/guide/00-airflow-essentials.md) · [`docs/guide/01-docker-essentials.md`](docs/guide/01-docker-essentials.md) — Airflow/Docker 운영 가이드

## 코드 품질

```bash
ruff check .          # 린트
mypy app/             # 타입 체크
```

## 개발 유의사항

- LLM 프롬프트는 코드가 아닌 `prompts/*.yaml`에서 관리
- `services/` 폴더명은 행위자 명사(-er/-or) 규칙 준수
- DB 모델 변경 시 `app/db/orm_models/<모델>.py` + `app/db/queries.py` 함께 수정 후 Alembic 마이그레이션 생성(`alembic revision --autogenerate` → `upgrade head`)
- `docs/` 문서 작성 규칙 — 헤더(작성자 `Kim minkyoung`·작성일 `YYYY-MM-DD`·범위 1줄)·본문 전 목차·코드 최소화·풋터 출처(`## 참고 자료`) 필수. 파일명 `NN-kebab-case.md` + 카테고리 폴더
- Airflow DAG는 `ExternalPythonOperator`로 **앱 전용 venv**(`/home/airflow/jangdokdae-venv`)에서 단계 실행(`expect_airflow=False`) — Airflow venv와 앱 의존성(SQLAlchemy 등)이 분리돼 있음. 자세한 건 [`docs/design/00-workflow-airflow.md`](docs/design/00-workflow-airflow.md)

## 파이프라인

- 수집 → 전처리 → 임베딩·클러스터링 → 엔티티 추출 → 분석 → 주린이 번역 생성
