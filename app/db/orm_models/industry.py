"""Industry ORM 모델 — GICS 산업(산업그룹 하위) 분류표."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class Industry(Base):
    __tablename__ = "industries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    industry_group_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("industry_groups.id"), nullable=False, index=True
    )
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)  # "반도체·반도체장비"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # "Semiconductors..."
    gics_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "453010"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
