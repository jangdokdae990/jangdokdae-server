"""IssueDocent ORM 모델 — 생성된 콘텐츠 (클러스터당 1행).

분류(news_analysis)에 이어 ContentGenerator가 만든 4-head 본문·첫 줄(hook)·연결 모듈·근거/용어
span을 클러스터당 1행으로 적재한다. 발행 전까지 is_published=False(설계 10 §7).
출처 배지(source_refs, 08 §8)는 §5 데이터 보강과 함께 후속 PR에서 추가한다.
"""

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class IssueDocent(Base):
    __tablename__ = "issue_docent"
    __table_args__ = (
        UniqueConstraint("cluster_id", name="uq_issue_docent_cluster"),
        # 온보딩 관심사(market/sector/company) 기반 피드 필터 — `:id = ANY(...)` 가속.
        Index("ix_issue_docent_market_ids", "market_ids", postgresql_using="gin"),
        Index("ix_issue_docent_sector_ids", "sector_ids", postgresql_using="gin"),
        Index("ix_issue_docent_company_ids", "company_ids", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_cluster.id"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # 온보딩 관심사 매칭용 백필 — 분류 origin(국내/해외)을 markets.id로 해소.
    market_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    # sector_tags를 sectors.id로 해소(news_analysis와 동일 소스). 미매칭은 제외.
    sector_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    # company_tags 이름을 company_entities.id로 해소(news_analysis와 동일 소스). 미매칭은 제외.
    company_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    # {"pain": "...", "neutral": "..."}
    hook_lines: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    # [{"label": "...", "question": "...", "answer": "..."}] × 4
    content_heads: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # [{"sector": "...", "sentiment": "...", "reason": "...", "company_candidates": [...]}]
    connection_module: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # [{"head": "...", "claim": "...", "sentence": "..."}]
    evidence_spans: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # [{"term": "...", "sentence": "..."}]
    term_spans: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    is_published: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
