"""Market ORM 모델 — 온보딩 1단계 시장 마스터.

코스피·코스닥·나스닥·S&P500·미국ETF·기타 해외 6분류. code는 거래소/지수 식별자(<=10자)이고
코스피/코스닥은 CompanyEntity.market(KOSPI/KOSDAQ)으로 매핑된다(queries.MARKET_CODE_TO_EXCHANGES).
description·tags는 온보딩 카드 표시용이다.
"""

from datetime import datetime

from sqlalchemy import ARRAY, Boolean, DateTime, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class Market(Base):
    __tablename__ = "markets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)  # "KOSPI" 등
    name_ko: Mapped[str] = mapped_column(String(50), nullable=False)  # "코스피"
    name_en: Mapped[str] = mapped_column(String(100), nullable=False)  # "KOSPI"
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)  # 카드 설명
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'::text[]"), nullable=False
    )  # 카드 대표 종목 태그
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), nullable=False
    )  # False=온보딩 노출 제외(데이터 미준비)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
