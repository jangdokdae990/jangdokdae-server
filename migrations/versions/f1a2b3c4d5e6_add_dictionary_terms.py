"""add dictionary_terms table

Revision ID: f1a2b3c4d5e6
Revises: 211e9d09101d, e8f1a2b3c4d5
Create Date: 2026-06-23 08:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = ("211e9d09101d", "e8f1a2b3c4d5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dictionary_terms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("term", sa.String(length=100), nullable=False),
        sa.Column("term_type", sa.String(length=20), nullable=False),
        sa.Column("definition", sa.Text(), nullable=False),
        sa.Column("example", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=True),
        sa.Column("first_issue_docent_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(now() AT TIME ZONE 'Asia/Seoul')"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["first_issue_docent_id"], ["issue_docent.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("term", name="uq_dictionary_terms_term"),
    )
    op.create_index("ix_dictionary_terms_status", "dictionary_terms", ["status"], unique=False)
    op.create_index("ix_dictionary_terms_type", "dictionary_terms", ["term_type"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_dictionary_terms_type", table_name="dictionary_terms")
    op.drop_index("ix_dictionary_terms_status", table_name="dictionary_terms")
    op.drop_table("dictionary_terms")
