"""Alembic 마이그레이션 환경.

연결 URL은 settings.sync_url(psycopg2)을 단일 출처로 쓰고, target_metadata는
app.db.base.Base.metadata로 둔다. 전체 ORM 모델을 import해 메타데이터에 등록해야
autogenerate가 모든 테이블을 인식한다.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import settings
from app.db.base import Base

# 모델 등록 — import만으로 Base.metadata에 테이블이 붙는다(autogenerate 대상).
from app.db.orm_models import (  # noqa: F401
    company_entity,
    disclosure,
    financial_statement,
    issue_docent,
    industry,
    industry_group,
    market,
    market_indicator,
    news,
    news_analysis,
    news_cluster,
    report_chunk,
    sector,
    stock_price,
    user,
    user_interest_company,
    user_interest_market,
    user_interest_sector,
)

config = context.config
# .ini의 sqlalchemy.url 대신 앱 설정(.env)에서 동기 드라이버 URL을 주입한다.
config.set_main_option("sqlalchemy.url", settings.sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """오프라인(SQL 스크립트) 모드."""
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """온라인(엔진 연결) 모드."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
