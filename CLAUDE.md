# 심화 프로젝트

- 프로젝트명: 장독대
- 프로젝트 뜻: 시장 독해를 대신 해드립니다를 줄여서 장독대
- 주린이(주식 초보자)를 위한 주식 큐레이션 · 학습 웹 서비스 플랫폼

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

## 테스트

```bash
pytest                # 전체 테스트
pytest --cov=app      # 커버리지 포함
```

## 참고 문서

- [`docs/rules/architecture.md`](docs/rules/architecture.md) — 폴더 구조 및 레이어 설명
- [`docs/rules/conventions.md`](docs/rules/conventions.md) — 파일명/클래스명/함수명 규칙
- [`.env.example`](.env.example) — 필요한 환경 변수 목록

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

## 파이프라인

- 수집 → 전처리 → 임베딩·클러스터링 → 엔티티 추출 → 분석 → Issue Docent 생성
