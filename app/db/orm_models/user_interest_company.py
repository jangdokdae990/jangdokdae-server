"""UserInterestCompany ORM 모델 — 사용자 관심 종목 (user×company_entity 조인)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class UserInterestCompany(Base):
    __tablename__ = "user_interest_companies"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_user_interest_company"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("company_entities.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
