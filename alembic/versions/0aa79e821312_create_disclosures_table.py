"""create disclosures table

Revision ID: 0aa79e821312
Revises: 21072120bdc0
Create Date: 2026-06-01 16:52:16.119327

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = '0aa79e821312'
down_revision: Union[str, Sequence[str], None] = '21072120bdc0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "disclosures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rcept_no", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("corp_name", sa.String(length=200), nullable=False),
        sa.Column("corp_code", sa.String(length=20), nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=True),
        sa.Column("disclosure_type", sa.String(length=50), nullable=False),
        sa.Column("disclosed_at", sa.DateTime(timezone=False), nullable=False),
        sa.Column(
            "is_analyzed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("(now() AT TIME ZONE 'Asia/Seoul')"),
            nullable=False,
        ),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.UniqueConstraint("rcept_no", name="uq_disclosure_rcept_no"),
    )
    # 미분석 공시 조회 최적화
    op.execute(
        "CREATE INDEX ix_disclosures_unanalyzed ON disclosures (is_analyzed, disclosed_at DESC) "
        "WHERE is_analyzed = false"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("disclosures")
