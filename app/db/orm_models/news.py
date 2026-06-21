"""News ORM 모델 — 수집한 뉴스 메타데이터."""

from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import KST_NOW, Base


class News(Base):
    __tablename__ = "news"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    # url은 더 이상 단일 멱등키가 아니다 — guid가 수집-시점 정확 중복키(아래)다.
    # ON CONFLICT은 한 제약만 타겟하므로 url unique를 유지하면 같은 url·다른 guid 전재
    # 기사에서 IntegrityError가 난다. url은 조회·중복 진단용 일반 인덱스로 강등한다.
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    # 수집-시점 정확 중복키 — 피드 제공 GUID, 없으면 정규화 URL(전처리에서 폴백). 멱등 저장 키.
    guid: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    rss_source: Mapped[str] = mapped_column(String(100), nullable=False)
    news_source: Mapped[str] = mapped_column(String(100), nullable=False)
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    is_filtered: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # 임베딩 유사도(cosine ≥ 0.95) 근접 중복 — 삭제 대신 soft flag로 표시한다.
    # 행을 보존해 FK 정합성·재수집 멱등을 지키며, 클러스터링·분석은 is_duplicate=false만 읽는다.
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    is_analyzed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # 같은 기사를 전재(재게재)한 매체 수 — 화제성 신호.
    # 파생 데이터(feature)일 뿐 단계 간 계약(게이트)이 아니다 — 어떤 단계도 읽는 조건으로 쓰지 않고
    # 중요도 스코어가 참고만 한다. 다층 중복 제거로 묶인 동일 기사군의 매체 수, 미검출 기본값 0.
    reprint_count: Mapped[int] = mapped_column(
        Integer, server_default=text("0"), default=0, nullable=False
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    __table_args__ = (
        # url 일반 인덱스 — unique 강등 후에도 조회·중복 진단용으로 유지(멱등키는 guid).
        Index("ix_news_url", "url"),
        # 종목 뉴스 조회용 부분 인덱스 — stock_code가 있는 행만 인덱싱(NER이 채운 종목 뉴스).
        Index(
            "ix_news_stock_code",
            "stock_code",
            postgresql_where=text("stock_code IS NOT NULL"),
        ),
        # 수집 시각 범위 조회용 — "당일 수집분" 창 필터링 시 풀스캔을 피한다.
        Index("ix_news_created_at", "created_at"),
        # 미처리 뉴스 조회용 부분 인덱스 — 분석 파이프라인이 미분석분만 최신순으로 조회.
        # DESC 기본 NULLS FIRST는 발행일 없는 기사를 앞에 두므로, NULLS LAST로 최신순을 보장한다.
        Index(
            "ix_news_unanalyzed",
            "is_analyzed",
            text("published_at DESC NULLS LAST"),
            postgresql_where=text("is_analyzed = false"),
        ),
        # 클러스터링·유사도 검색용 HNSW 인덱스(cosine). 누적 후 추가하면 빌드가 느려 미리 생성한다.
        Index(
            "ix_news_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
