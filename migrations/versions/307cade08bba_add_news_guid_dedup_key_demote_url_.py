"""add news.guid dedup key, demote url unique

Revision ID: 307cade08bba
Revises: 1cdcb76394bf
Create Date: 2026-06-19 10:54:31.344644

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '307cade08bba'
down_revision: Union[str, Sequence[str], None] = '1cdcb76394bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    guid를 수집-시점 정확 중복키(unique)로 도입하고 url unique를 일반 인덱스로 강등한다.
    ON CONFLICT은 한 제약만 타겟하므로 url unique를 유지하면 같은 url·다른 guid 전재
    기사에서 IntegrityError가 난다(설계 02 §7·§8.2).
    """
    # 1) guid 추가 — 기존 행 백필 위해 우선 nullable로 만든다.
    op.add_column('news', sa.Column('guid', sa.String(length=500), nullable=True))
    # 2) 기존 행 백필: guid = url. 기존 url은 유일하므로 guid 유일성이 그대로 보장된다.
    op.execute('UPDATE news SET guid = url WHERE guid IS NULL')
    # 3) 백필 후 NOT NULL 적용.
    op.alter_column('news', 'guid', existing_type=sa.String(length=500), nullable=False)
    # 4) guid unique 제약 추가(멱등 충돌키) + url unique 강등(일반 인덱스로 교체).
    op.create_unique_constraint('news_guid_key', 'news', ['guid'])
    op.drop_constraint('news_url_key', 'news', type_='unique')
    op.create_index('ix_news_url', 'news', ['url'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_news_url', table_name='news')
    op.create_unique_constraint('news_url_key', 'news', ['url'])
    op.drop_constraint('news_guid_key', 'news', type_='unique')
    op.drop_column('news', 'guid')
