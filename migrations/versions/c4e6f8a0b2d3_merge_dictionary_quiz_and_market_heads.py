"""merge dictionary quiz and market heads

Revision ID: c4e6f8a0b2d3
Revises: b3d5f7a9c1e2, e89f78e7e898
Create Date: 2026-06-23 10:45:00.000000

"""

from typing import Sequence, Union

revision: str = "c4e6f8a0b2d3"
down_revision: Union[str, Sequence[str], None] = ("b3d5f7a9c1e2", "e89f78e7e898")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
