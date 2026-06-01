"""create financial_statements table

Revision ID: 34e85c2bad11
Revises: 769d57a4ce4f
Create Date: 2026-06-01 17:42:05.597059

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '34e85c2bad11'
down_revision: Union[str, Sequence[str], None] = '769d57a4ce4f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "financial_statements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("corp_code", sa.String(length=20), nullable=False),
        sa.Column("corp_name", sa.String(length=200), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("quarter", sa.Integer(), nullable=False),
        sa.Column("revenue", sa.BigInteger(), nullable=True),
        sa.Column("operating_income", sa.BigInteger(), nullable=True),
        sa.Column("net_income", sa.BigInteger(), nullable=True),
        sa.Column("total_assets", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("(now() AT TIME ZONE 'Asia/Seoul')"),
            nullable=False,
        ),
        sa.UniqueConstraint("corp_code", "year", "quarter", name="uq_financial_statement"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("financial_statements")
