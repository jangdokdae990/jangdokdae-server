"""ensure dictionary_terms table exists

Revision ID: b3d5f7a9c1e2
Revises: a2c4e6f8b0d1
Create Date: 2026-06-23 10:20:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "b3d5f7a9c1e2"
down_revision: Union[str, Sequence[str], None] = "a2c4e6f8b0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS dictionary_terms (
            id SERIAL PRIMARY KEY,
            term VARCHAR(100) NOT NULL,
            term_type VARCHAR(20) NOT NULL,
            definition TEXT NOT NULL,
            example TEXT NULL,
            source VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL,
            model_name VARCHAR(100) NULL,
            first_issue_docent_id INTEGER NULL REFERENCES issue_docent(id),
            created_at TIMESTAMP NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Seoul'),
            updated_at TIMESTAMP NULL,
            CONSTRAINT uq_dictionary_terms_term UNIQUE (term)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dictionary_terms_status "
        "ON dictionary_terms (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_dictionary_terms_type "
        "ON dictionary_terms (term_type)"
    )


def downgrade() -> None:
    # Repair migration: f1 owns the table lifecycle on clean databases.
    pass
