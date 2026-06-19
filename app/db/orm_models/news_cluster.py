"""NewsCluster ORM 모델 — 클러스터링 산출물 (클러스터당 1행).

같은 이슈로 묶인 기사 그룹을 1행으로 적재한다. 분석 단계가 importance 내림차순으로 읽어
상위 이슈를 인계받는다. embedding은 기사당 값이라 `news`에 남고, 여기엔 클러스터 식별·소속·
중요도 스코어만 둔다.
"""

from datetime import date, datetime

from sqlalchemy import ARRAY, Date, DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class NewsCluster(Base):
    __tablename__ = "news_cluster"
    __table_args__ = (
        # 같은 실행 일자·대표 기사 조합은 1행만 — 재실행 시 중복 적재를 막는 멱등 키.
        UniqueConstraint("run_date", "representative_news_id", name="uq_news_cluster_run_rep"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)  # 클러스터링 실행 일자
    # 대표 기사 = member_news_ids[0] (클러스터 중심 근접순)
    representative_news_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news.id"), nullable=False
    )
    # 소속 기사 id (중심 근접순 정렬 — 본문 fetch fallback 순서로도 쓰임)
    member_news_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)  # 클러스터 기사 수
    importance: Mapped[float] = mapped_column(Float, nullable=False)  # 복합 중요도 [0,1]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
