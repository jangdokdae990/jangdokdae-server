"""StockPrice ORM 모델 — 일봉 시계열."""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class StockPrice(Base):
    __tablename__ = "stock_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stock_code: Mapped[str] = mapped_column(String(20), nullable=False)  # 종목 코드 "005930"
    name: Mapped[str] = mapped_column(String(100), nullable=False)       # 종목명 "삼성전자"
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False)
    market_cap: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # pykrx 보완(후속)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)  # 거래일
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )

    # 같은 종목·같은 날 중복 방지 (save_tool on_conflict 대상)
    __table_args__ = (UniqueConstraint("stock_code", "date", name="uq_stock_code_date"),)
