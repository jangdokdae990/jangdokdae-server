"""NewsAnalysis ORM 모델 — 분류 결과 (클러스터당 1행).

EmbeddingClusterer가 적재한 클러스터(이슈)를 분석 단계(NewsAnalyzer, →10)가 받아 분류한 결과를
클러스터당 1행으로 적재한다. 콘텐츠 본문은 grain이 같지만 책임이 달라 issue_docent로 분리한다.
신뢰도가 낮으면 needs_review=True로 검수 큐 대상이 된다(설계 10 §3·09 P0).
"""

from datetime import datetime

from sqlalchemy import (
    ARRAY,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class NewsAnalysis(Base):
    __tablename__ = "news_analysis"
    __table_args__ = (
        # 클러스터당 분류 1행 — 재실행(재시도) 시 ON CONFLICT로 중복 적재를 막는 멱등 키.
        UniqueConstraint("cluster_id", name="uq_news_analysis_cluster"),
        # "특정 기업/섹터를 언급한 이슈" 관계형 조회용 — `:id = ANY(...)` 가속.
        Index("ix_news_analysis_company_ids", "company_ids", postgresql_using="gin"),
        Index("ix_news_analysis_sector_ids", "sector_ids", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("news_cluster.id"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False)  # 회사 | 업종·테마 | 시장 전체
    frame: Mapped[str] = mapped_column(String(20), nullable=False)  # 내부 코드 EARNINGS..PRICE
    origin: Mapped[str] = mapped_column(String(10), nullable=False)  # 국내 | 해외
    direction: Mapped[str] = mapped_column(String(10), nullable=False)  # 상승 | 하락 | 중립
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sector_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    # [{"name": "...", "role": "primary|mentioned"}]
    company_tags: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    # company_tags 이름을 company_entities.id로 해소한 백필(미매칭 제외, 원문은 태그에 보존).
    company_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    # sector_tags를 sectors.id로 해소한 백필(sectors 마스터가 단일 소스). 미매칭은 제외.
    sector_ids: Mapped[list[int]] = mapped_column(
        ARRAY(Integer), nullable=False, server_default=text("'{}'::integer[]")
    )
    term_tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    needs_review: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # 투자 관련성 게이트(평가 04). false면 비투자성(홍보·사회공헌·부고 등)이라 issue_docent를
    # 적재하지 않는다(relevance 필터). 기본 true — 기존 행·관련 뉴스 호환.
    is_investment_relevant: Mapped[bool] = mapped_column(
        Boolean, server_default=text("true"), default=True, nullable=False
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
