"""ensure company entity markets

Revision ID: e6a8c0d2f4b6
Revises: d5f7a9c1e3b4
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e6a8c0d2f4b6"
down_revision: str | Sequence[str] | None = "d5f7a9c1e3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE company_entities "
        "ADD COLUMN IF NOT EXISTS markets varchar(10)[] NOT NULL DEFAULT '{}'::text[]"
    )
    op.execute(
        "UPDATE company_entities SET markets = ARRAY[market] "
        "WHERE cardinality(markets) = 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE company_entities DROP COLUMN IF EXISTS markets")
