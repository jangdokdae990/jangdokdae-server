"""Market ORM 모델 — 온보딩 1단계 시장 마스터.

시장은 거래소·지수 단위다 — code는 KOSPI·KOSDAQ·NASDAQ·SP500·US_ETF·GLOBAL(기타 해외 시장).
국내(KOSPI/KOSDAQ)는 CompanyEntity.market과 code가 그대로 일치한다. 정본·시드 정합화는 설계 14 참조.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "KOSPI"|"NASDAQ"|…
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)  # "코스피"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # "KOSPI"
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )  # False=온보딩 노출 제외(데이터 미준비)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
