"""create news table with pgvector

Revision ID: bac51ac9aec1
Revises: 
Create Date: 2026-06-01 15:26:02.954153

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = 'bac51ac9aec1'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Vector 컬럼보다 먼저 확장 활성화
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "news",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("rss_source", sa.String(length=100), nullable=False),
        sa.Column("news_source", sa.String(length=100), nullable=False),
        sa.Column("symbol", sa.String(length=20), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("preprocessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_analyzed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
    )

    # url 중복 방지 (save_tool on_conflict의 대상)
    op.create_index("uq_news_url", "news", ["url"], unique=True)

    # 미분석 뉴스 조회 최적화 (분석 파이프라인이 자주 호출)
    op.execute(
        "CREATE INDEX ix_news_unanalyzed ON news (is_analyzed, published_at DESC) "
        "WHERE is_analyzed = false"
    )

    # pgvector HNSW — 클러스터링·유사도 검색 성능. 빈 테이블에서 즉시 빌드
    op.execute(
        "CREATE INDEX ix_news_embedding ON news USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("news")  # 인덱스는 테이블과 함께 삭제됨
