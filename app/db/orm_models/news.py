"""News ORM 모델 — 수집한 뉴스 메타데이터."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    rss_source: Mapped[str] = mapped_column(String(100), nullable=False)   # 어느 RSS 피드
    news_source: Mapped[str] = mapped_column(String(100), nullable=False)  # 본문 출처(언론사)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 종목 뉴스 — NER이 채움
    # 발행 시각(KST, naive). 일부 RSS 기사는 발행일이 없음 → nullable. 24시간 필터는 Phase 4가 처리
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    # core pg_insert는 Python default 미적용 → server_default로 DB 기본값(KST) 지정
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    preprocessed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )  # NULL=미처리 (KST)
    is_analyzed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
