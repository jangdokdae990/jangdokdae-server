"""IndustryGroup ORM 모델 — GICS 산업그룹(섹터 하위) 분류표."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class IndustryGroup(Base):
    __tablename__ = "industry_groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sectors.id"), nullable=False, index=True
    )
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)  # "자본재"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # "Capital Goods"
    gics_code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "2010"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
