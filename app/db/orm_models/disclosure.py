"""Disclosure ORM 모델 — DART 공시."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class Disclosure(Base):
    __tablename__ = "disclosures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rcept_no: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # DART 접수번호
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)  # 원문, 후속 fetch
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    corp_code: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # DART 기업 고유번호
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # 상장사만
    disclosure_type: Mapped[str] = mapped_column(String(50), nullable=False)  # "A" | "B"
    # 공시 일시 (KST naive)
    disclosed_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    is_analyzed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    # 유사도 검색용 HNSW 인덱스 (cosine).
    __table_args__ = (
        Index(
            "ix_disclosures_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
