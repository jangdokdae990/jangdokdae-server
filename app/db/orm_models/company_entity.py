"""CompanyEntity ORM 모델 — 추적 기업 유니버스 및 Entity Linking 기준 사전."""

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class CompanyEntity(Base):
    __tablename__ = "company_entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)  # "005930"
    name_ko: Mapped[str] = mapped_column(String(200), nullable=False)  # "삼성전자"
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 영문명
    # Entity Linking용 별칭 (예: ["삼전", "SSNLF"])
    aliases: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    corp_code: Mapped[str | None] = mapped_column(String(20), nullable=True)  # DART 고유코드
    market: Mapped[str] = mapped_column(String(10), nullable=False)  # "KOSPI" | "KOSDAQ"
    sector_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sectors.id"), nullable=True, index=True
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )  # False=수집 비활성화
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    # onupdate는 ORM UPDATE 시에만 발화 — core upsert(DO NOTHING/DO UPDATE)에는 미적용
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), onupdate=KST_NOW, nullable=True
    )
