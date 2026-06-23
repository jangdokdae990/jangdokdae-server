"""merge global index markets and dictionary quiz heads

Revision ID: bef094fbc038
Revises: c4e6f8a0b2d3, c4e8b1a9f2d6
"""

from collections.abc import Sequence

revision: str = "bef094fbc038"
down_revision: str | Sequence[str] | None = ("c4e6f8a0b2d3", "c4e8b1a9f2d6")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
