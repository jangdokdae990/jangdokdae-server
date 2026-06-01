"""rename stock_prices symbol to stock_code

Revision ID: 21072120bdc0
Revises: c120d96d3a95
Create Date: 2026-06-01 16:43:24.384578

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '21072120bdc0'
down_revision: Union[str, Sequence[str], None] = 'c120d96d3a95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column("stock_prices", "symbol", new_column_name="stock_code")
    op.execute("ALTER TABLE stock_prices RENAME CONSTRAINT uq_stock_symbol_date TO uq_stock_code_date")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE stock_prices RENAME CONSTRAINT uq_stock_code_date TO uq_stock_symbol_date")
    op.alter_column("stock_prices", "stock_code", new_column_name="symbol")
