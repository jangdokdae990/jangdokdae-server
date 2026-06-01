"""market_indicator unique nulls not distinct

Revision ID: 769d57a4ce4f
Revises: cbf1fc231511
Create Date: 2026-06-01 17:30:11.543344

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '769d57a4ce4f'
down_revision: Union[str, Sequence[str], None] = 'cbf1fc231511'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # ECOS 지표는 currency=NULL. 기본 UNIQUE는 NULL을 distinct 취급해 중복 허용 →
    # NULLS NOT DISTINCT로 재생성해 (type, NULL, date) UPSERT 멱등성 보장 (PG15+)
    op.execute("ALTER TABLE market_indicators DROP CONSTRAINT uq_market_indicator")
    op.execute(
        "ALTER TABLE market_indicators ADD CONSTRAINT uq_market_indicator "
        "UNIQUE NULLS NOT DISTINCT (indicator_type, currency, date)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TABLE market_indicators DROP CONSTRAINT uq_market_indicator")
    op.execute(
        "ALTER TABLE market_indicators ADD CONSTRAINT uq_market_indicator "
        "UNIQUE (indicator_type, currency, date)"
    )
