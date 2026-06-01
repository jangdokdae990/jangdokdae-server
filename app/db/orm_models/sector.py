"""Sector ORM 모델 — WICS·GICS 섹터 분류 기준표."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class Sector(Base):
    __tablename__ = "sectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)  # "IT"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # "Information Technology"
    wics_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "4510"
    gics_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "45"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
