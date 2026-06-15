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
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    rss_source: Mapped[str] = mapped_column(String(100), nullable=False)   # 어느 RSS 피드
    news_source: Mapped[str] = mapped_column(String(100), nullable=False)  # 본문 출처(언론사)
    # 종목 뉴스 — NER이 채움
    stock_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 발행 시각(KST, naive). 일부 RSS 기사는 발행일이 없음 → nullable. 24시간 필터는 Phase 4가 처리
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    # core pg_insert는 Python default 미적용 → server_default로 DB 기본값(KST) 지정
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False), server_default=KST_NOW, nullable=False
    )
    # 전처리에서 분석 대상에서 제외됨(24h 초과·제목 중복). True면 임베딩·분석 스킵.
    # is_analyzed(분석 완료)와 구분 — 통과율 집계 시 의미 오염 방지
    is_filtered: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    # 임베딩 유사도(cosine ≥ 0.95) 근접 중복 — 삭제 대신 soft flag로 표시(→ 설계 05 §4.2).
    # 행을 보존해 news_cluster FK 정합성·URL 멱등 재수집 방지·추적성을 지킨다.
    # 클러스터링·분석은 is_duplicate=false만 읽는다.
    is_duplicate: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    is_analyzed: Mapped[bool] = mapped_column(
        Boolean, server_default=text("false"), default=False, nullable=False
    )
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)

    __table_args__ = (
        # 종목 뉴스 조회용 부분 인덱스 — stock_code가 있는 행만 인덱싱(NER이 채운 종목 뉴스).
        Index(
            "ix_news_stock_code",
            "stock_code",
            postgresql_where=text("stock_code IS NOT NULL"),
        ),
        # 수집 시각 범위 조회용 — dedup·클러스터링이 "당일 수집분" 창(created_at >= cutoff)으로
        # 매 실행 필터링하므로, 테이블이 일 단위로 누적 성장해도 풀스캔을 피한다.
        Index("ix_news_created_at", "created_at"),
        # 미처리 뉴스 조회용 부분 인덱스 — 분석 파이프라인이 미분석분만 최신순으로 자주 조회.
        # 분석 완료 행은 인덱스에서 빠져 크기·스캔 비용이 미처리분에만 비례한다(설계 02 §8.2).
        # published_at은 nullable(RSS 다수가 발행일 없음)이고 DESC 기본은 NULLS FIRST라
        # 발행일 없는 기사가 앞에 와 '최신순'을 해친다 → NULLS LAST로 발행일 있는 최신순을 보장.
        Index(
            "ix_news_unanalyzed",
            "is_analyzed",
            text("published_at DESC NULLS LAST"),
            postgresql_where=text("is_analyzed = false"),
        ),
        # 클러스터링·유사도 검색용 HNSW 인덱스(cosine). 벡터가 쌓이기 전 미리 생성한다
        # — 누적 후 추가하면 인덱스 빌드가 오래 걸린다(설계 02 §8.2).
        Index(
            "ix_news_embedding",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
