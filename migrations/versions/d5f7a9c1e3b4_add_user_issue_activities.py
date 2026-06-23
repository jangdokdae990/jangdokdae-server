"""add user issue activities

Revision ID: d5f7a9c1e3b4
Revises: bef094fbc038
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5f7a9c1e3b4"
down_revision: str | Sequence[str] | None = "bef094fbc038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_issue_activities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "issue_docent_id",
            sa.Integer(),
            sa.ForeignKey("issue_docent.id"),
            nullable=False,
        ),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("bookmarked_at", sa.DateTime(), nullable=True),
        sa.Column(
            "quiz_answers",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "quiz_results",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("quiz_correct_count", sa.Integer(), nullable=True),
        sa.Column("quiz_total_count", sa.Integer(), nullable=True),
        sa.Column("quiz_completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(now() AT TIME ZONE 'Asia/Seoul')"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "issue_docent_id", name="uq_user_issue_activity"),
    )
    op.create_index("ix_user_issue_activities_user_id", "user_issue_activities", ["user_id"])
    op.create_index(
        "ix_user_issue_activities_issue_docent_id",
        "user_issue_activities",
        ["issue_docent_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_issue_activities_issue_docent_id", table_name="user_issue_activities")
    op.drop_index("ix_user_issue_activities_user_id", table_name="user_issue_activities")
    op.drop_table("user_issue_activities")
