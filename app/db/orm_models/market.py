"""Market ORM 모델 — 온보딩 1단계 시장 마스터.

시장은 국내/해외 큰 분류다. CompanyEntity.market(KOSPI/KOSDAQ)은 국내(code="KR")로 매핑된다.
해외(code="OVERSEAS")는 데이터 준비 전까지 is_active=False로 둔다.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "KR"|"OVERSEAS"
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)  # "국내"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # "Domestic"
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )  # False=온보딩 노출 제외(데이터 미준비)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
