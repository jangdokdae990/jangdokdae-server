"""사용자별 이슈 읽기·저장·최근 퀴즈 상태."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class UserIssueActivity(Base):
    __tablename__ = "user_issue_activities"
    __table_args__ = (
        UniqueConstraint("user_id", "issue_docent_id", name="uq_user_issue_activity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    issue_docent_id: Mapped[int] = mapped_column(
        ForeignKey("issue_docent.id"), nullable=False, index=True
    )
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    bookmarked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    quiz_answers: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    quiz_results: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    quiz_correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiz_total_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quiz_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), onupdate=KST_NOW, nullable=True
    )
