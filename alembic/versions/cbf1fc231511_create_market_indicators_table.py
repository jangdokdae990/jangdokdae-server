"""create market_indicators table

Revision ID: cbf1fc231511
Revises: 0aa79e821312
Create Date: 2026-06-01 17:12:16.420829

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cbf1fc231511'
down_revision: Union[str, Sequence[str], None] = '0aa79e821312'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "market_indicators",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("indicator_type", sa.String(length=50), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=True),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            server_default=sa.text("(now() AT TIME ZONE 'Asia/Seoul')"),
            nullable=False,
        ),
        sa.UniqueConstraint("indicator_type", "currency", "date", name="uq_market_indicator"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("market_indicators")
