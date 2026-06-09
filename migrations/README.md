# 데이터베이스 마이그레이션 (Alembic)

장독대 서버의 DB 스키마 버전 관리 디렉터리입니다. ORM 모델([`app/db/orm_models/`](../app/db/orm_models/))을 단일 출처(source of truth)로 두고, Alembic이 모델과 실제 DB의 차이를 추적·반영합니다.

- DB: Neon(PostgreSQL) + pgvector
- 도구: Alembic 1.18 / SQLAlchemy
- 설정: [`alembic.ini`](../alembic.ini), 환경 스크립트: [`env.py`](env.py)

## 구조

```
migrations/
├── env.py                 # 마이그레이션 실행 환경 (URL 주입, 모델 등록)
├── script.py.mako         # 새 마이그레이션 파일 템플릿
└── versions/              # 실제 마이그레이션 스크립트 (리비전별)
    └── e91033167c44_baseline_current_schema.py  # 최초 baseline
```

## 동작 방식

- **연결 URL**: `.env`의 `database_url`을 읽어 `settings.sync_url`(psycopg2 동기 드라이버)로 변환해 주입합니다. `alembic.ini`의 `sqlalchemy.url`(더미 값)은 사용하지 않습니다. 즉 **마이그레이션도 앱과 같은 `.env` DB를 바라봅니다.**
- **메타데이터**: `target_metadata = Base.metadata`. [`env.py`](env.py)에서 모든 ORM 모델을 import해야 autogenerate가 전체 테이블을 인식합니다. **새 모델을 추가하면 반드시 [`env.py`](env.py)의 import 목록에도 추가하세요.** (빠지면 autogenerate가 해당 테이블을 못 보고 drop 처리할 수 있음)
- **pgvector**: baseline 마이그레이션이 `CREATE EXTENSION IF NOT EXISTS vector`를 먼저 실행한 뒤 `Vector` 컬럼 테이블을 생성합니다. 새 DB에 적용할 때도 이 순서가 유지됩니다.
- **타입 비교**: `compare_type=True`로 컬럼 타입 변경도 감지합니다.

## 사용법

> 사전 조건: `.env`에 `database_url` 설정, `uv sync`로 의존성 설치 완료. 명령은 프로젝트 루트에서 실행합니다.

```bash
# 현재 DB 리비전 확인
uv run alembic current

# 최신 스키마로 적용
uv run alembic upgrade head

# 모델 변경 후 마이그레이션 자동 생성 (반드시 생성된 파일을 검토)
uv run alembic revision --autogenerate -m "add xxx column"

# 한 단계 롤백
uv run alembic downgrade -1

# 마이그레이션 이력 보기
uv run alembic history
```

## 워크플로 (모델 변경 시)

1. [`app/db/orm_models/`](../app/db/orm_models/)에서 ORM 모델 수정 또는 추가
2. 새 모델 파일이면 [`env.py`](env.py)의 import 목록에 추가
3. `uv run alembic revision --autogenerate -m "변경 요약"`
4. `versions/`에 생성된 스크립트를 **직접 검토** — autogenerate는 인덱스명·기본값·데이터 이전 등을 놓칠 수 있음
5. `uv run alembic upgrade head`로 적용 후 동작 확인
6. 마이그레이션 파일을 커밋

## 주의사항

- autogenerate 결과는 항상 검토 후 적용합니다. 특히 컬럼 rename은 drop+add로 잡혀 데이터가 유실될 수 있습니다.
- `versions/__pycache__/`는 커밋하지 않습니다.
- baseline(`e91033167c44`)은 현재 스키마 전체를 담은 시작점이며, 빈 DB는 `upgrade head` 한 번으로 전체 스키마가 생성됩니다.
