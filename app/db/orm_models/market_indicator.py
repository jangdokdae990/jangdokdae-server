"""MarketIndicator ORM 모델 — 환율·금리·거시지표 시계열."""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class MarketIndicator(Base):
    __tablename__ = "market_indicators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # "exchange_rate" | "interest_rate" | "cpi" | "kospi" | "m2"
    indicator_type: Mapped[str] = mapped_column(String(50), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(10), nullable=True)  # 환율만: "USD"·"JPY"
    value: Mapped[float] = mapped_column(Float, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )

    # currency가 NULL인 ECOS 지표도 멱등 UPSERT 되도록 NULLS NOT DISTINCT (PG15+)
    __table_args__ = (
        UniqueConstraint(
            "indicator_type",
            "currency",
            "date",
            name="uq_market_indicator",
            postgresql_nulls_not_distinct=True,
        ),
    )
