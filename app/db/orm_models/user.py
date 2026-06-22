"""User ORM 모델 — OAuth 가입 사용자.

provider별 계정을 (provider, provider_user_id)로 식별한다. 비밀번호는 보관하지 않는다
(소셜 로그인 전용). onboarding_completed_at이 NULL이면 온보딩 미완료로 본다.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # 같은 provider 내 동일 계정은 1행 — 콜백 upsert의 조회·멱등 키.
        UniqueConstraint("provider", "provider_user_id", name="uq_users_provider_account"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)  # "kakao"|"google"
    provider_user_id: Mapped[str] = mapped_column(String(100), nullable=False)  # provider 고유 id
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    nickname: Mapped[str | None] = mapped_column(String(100), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # NULL = 온보딩 미완료 — 콜백 후 라우팅 분기 기준.
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), onupdate=KST_NOW, nullable=True
    )
