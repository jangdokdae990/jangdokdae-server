"""SQLAlchemy 선언적 Base, 비동기 엔진·세션, ORM 공통 정의."""

import ssl
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# 시각 컬럼 server_default — timezone 없는 한국 시각(KST)으로 저장한다.
# Neon pooler가 세션 타임존을 강제하고 asyncpg는 timestamptz를 UTC로 돌려줘서,
# timestamptz로는 KST 표시가 보장되지 않기 때문(한국 전용 서비스 → naive KST가 단순·명확).
KST_NOW = text("(now() AT TIME ZONE 'Asia/Seoul')")


# Neon은 SSL 필수. asyncpg는 sslmode 쿼리 대신 ssl 컨텍스트를 connect_args로 받는다.
# statement_cache_size=0 — Neon pooler(PgBouncer)에서 prepared statement 충돌 방지.
_ssl_context = ssl.create_default_context()
engine = create_async_engine(
    settings.async_url,
    connect_args={"ssl": _ssl_context, "statement_cache_size": 0},
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
