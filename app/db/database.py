"""SQLAlchemy 선언적 Base와 비동기 엔진·세션."""

import ssl
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    pass


# Neon은 SSL 필수. asyncpg는 sslmode 쿼리 대신 ssl 컨텍스트를 connect_args로 받는다.
# statement_cache_size=0 — Neon pooler(PgBouncer)에서 prepared statement 충돌 방지.
# 시각 컬럼은 naive KST로 저장하므로 세션 타임존에 의존하지 않는다.
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
