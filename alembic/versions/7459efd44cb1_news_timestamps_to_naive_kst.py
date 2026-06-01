"""news timestamps to naive KST

Revision ID: 7459efd44cb1
Revises: 9f554fce279d
Create Date: 2026-06-01 16:15:39.079123

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7459efd44cb1'
down_revision: Union[str, Sequence[str], None] = '9f554fce279d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # timestamptz → timestamp(without tz). 기존 값은 KST 벽시계로 변환해 보존
    for col in ("published_at", "created_at", "preprocessed_at"):
        op.alter_column(
            "news",
            col,
            type_=sa.DateTime(timezone=False),
            postgresql_using=f"{col} AT TIME ZONE 'Asia/Seoul'",
        )
    # created_at 기본값을 KST now()로
    op.alter_column(
        "news",
        "created_at",
        server_default=sa.text("(now() AT TIME ZONE 'Asia/Seoul')"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "news", "created_at", server_default=sa.text("now()")
    )
    for col in ("published_at", "created_at", "preprocessed_at"):
        op.alter_column(
            "news",
            col,
            type_=sa.DateTime(timezone=True),
            postgresql_using=f"{col} AT TIME ZONE 'Asia/Seoul'",
        )
