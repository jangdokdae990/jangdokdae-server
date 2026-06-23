"""add issue_docent market, sector, and company ids

Revision ID: f3a7c9d2e1b8
Revises: e89f78e7e898
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a7c9d2e1b8"
down_revision: str | Sequence[str] | None = "e89f78e7e898"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARRAY_COLUMNS = ("market_ids", "sector_ids", "company_ids")


def upgrade() -> None:
    for column in _ARRAY_COLUMNS:
        op.add_column(
            "issue_docent",
            sa.Column(
                column,
                sa.ARRAY(sa.Integer()),
                server_default=sa.text("'{}'::integer[]"),
                nullable=False,
            ),
        )
        op.create_index(
            f"ix_issue_docent_{column}",
            "issue_docent",
            [column],
            postgresql_using="gin",
        )


def downgrade() -> None:
    for column in reversed(_ARRAY_COLUMNS):
        op.drop_index(f"ix_issue_docent_{column}", table_name="issue_docent")
        op.drop_column("issue_docent", column)
