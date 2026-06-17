"""ReportChunk ORM 모델 — 사업보고서 섹션 청크 (RAG 소스)."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class ReportChunk(Base):
    __tablename__ = "report_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(20), nullable=False)    # DART 기업 고유코드
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    report_year: Mapped[int] = mapped_column(Integer, nullable=False)      # 사업연도
    rcept_no: Mapped[str] = mapped_column(
        String(20), nullable=False, index=True
    )  # DART 접수번호
    # "business_summary" | "director_analysis" | "audit_opinion"
    chunk_type: Mapped[str] = mapped_column(String(50), nullable=False)
    subsection: Mapped[str] = mapped_column(String(500), nullable=False, default="")  # 소제목
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("corp_code", "report_year", "chunk_type", "subsection",
                         name="uq_report_chunk"),
        # RAG 유사도 검색용 HNSW 인덱스 (cosine).
        Index(
            "ix_report_chunks_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
