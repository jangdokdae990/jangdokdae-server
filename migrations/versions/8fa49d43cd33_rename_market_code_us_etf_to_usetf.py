"""rename market code US_ETF to USETF

Revision ID: 8fa49d43cd33
Revises: f3a7c9d2e1b8
"""

from collections.abc import Sequence

from alembic import op

revision: str = "8fa49d43cd33"
down_revision: str | Sequence[str] | None = "f3a7c9d2e1b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("UPDATE markets SET code = 'USETF' WHERE code = 'US_ETF'")
    op.execute("UPDATE company_entities SET market = 'USETF' WHERE market = 'US_ETF'")


def downgrade() -> None:
    op.execute("UPDATE company_entities SET market = 'US_ETF' WHERE market = 'USETF'")
    op.execute("UPDATE markets SET code = 'US_ETF' WHERE code = 'USETF'")
