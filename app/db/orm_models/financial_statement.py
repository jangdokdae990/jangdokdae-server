"""FinancialStatement ORM 모델 — 분기별 핵심 재무 수치 (DART)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class FinancialStatement(Base):
    __tablename__ = "financial_statements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    corp_code: Mapped[str] = mapped_column(String(20), nullable=False)  # DART 기업 고유번호
    corp_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # 원천 공시 접수번호 — disclosures·report_chunks와 같은 사업보고서를 잇는 추적 키
    rcept_no: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    quarter: Mapped[int] = mapped_column(Integer, nullable=False)  # 1~4 (사업보고서=4)
    # 수치 출처 재무제표 구분 — CFS=연결 / OFS=개별. 연도 간 비교 시 출처 추적용
    # (구버전 적재분·미상은 NULL). 한 (corp_code,year,quarter)당 한 출처만 저장한다.
    fs_div: Mapped[str | None] = mapped_column(String(3), nullable=True)
    revenue: Mapped[int | None] = mapped_column(BigInteger, nullable=True)           # 매출액
    operating_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # 영업이익
    net_income: Mapped[int | None] = mapped_column(BigInteger, nullable=True)        # 당기순이익
    total_assets: Mapped[int | None] = mapped_column(BigInteger, nullable=True)      # 자산총계
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )

    __table_args__ = (
        UniqueConstraint("corp_code", "year", "quarter", name="uq_financial_statement"),
    )
