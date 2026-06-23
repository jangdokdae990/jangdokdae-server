"""DictionaryTerm ORM 모델 — 본문 용어 툴팁과 사전 화면의 공통 저장소."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class DictionaryTerm(Base):
    __tablename__ = "dictionary_terms"
    __table_args__ = (
        UniqueConstraint("term", name="uq_dictionary_terms_term"),
        Index("ix_dictionary_terms_status", "status"),
        Index("ix_dictionary_terms_type", "term_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    term: Mapped[str] = mapped_column(String(100), nullable=False)
    term_type: Mapped[str] = mapped_column(String(20), nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    example: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="llm")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="candidate")
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    first_issue_docent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("issue_docent.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), onupdate=KST_NOW, nullable=True
    )
