"""add news_analysis and issue_docent tables

분석 단계(NewsAnalyzer, 설계 10)의 산출물 2종을 추가한다 — 클러스터(이슈)당 분류 결과
(news_analysis)와 생성 콘텐츠(issue_docent). 둘 다 cluster_id(news_cluster.id) 유니크로
재실행 멱등(ON CONFLICT DO NOTHING). 본 마이그레이션은 ORM 모델에 맞춰 수기 작성했다
(.env/DB 없이 autogenerate 불가한 환경) — 스키마는 app/db/orm_models/{news_analysis,issue_docent}.py와 일치.

Revision ID: a1b2c3d4e5f6
Revises: fa6e579bc7dc
Create Date: 2026-06-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'fa6e579bc7dc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KST_NOW = sa.text("(now() AT TIME ZONE 'Asia/Seoul')")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'news_analysis',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(length=20), nullable=False),
        sa.Column('frame', sa.String(length=20), nullable=False),
        sa.Column('origin', sa.String(length=10), nullable=False),
        sa.Column('direction', sa.String(length=10), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False),
        sa.Column('sector_tags', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column('company_tags', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('term_tags', sa.ARRAY(sa.Text()), server_default=sa.text("'{}'::text[]"), nullable=False),
        sa.Column('needs_review', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('analyzed_at', sa.DateTime(), server_default=_KST_NOW, nullable=False),
        sa.ForeignKeyConstraint(['cluster_id'], ['news_cluster.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cluster_id', name='uq_news_analysis_cluster'),
    )
    op.create_table(
        'issue_docent',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('cluster_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=500), nullable=False),
        sa.Column('hook_lines', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('content_heads', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('connection_module', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('evidence_spans', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('term_spans', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('is_published', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=_KST_NOW, nullable=False),
        sa.ForeignKeyConstraint(['cluster_id'], ['news_cluster.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('cluster_id', name='uq_issue_docent_cluster'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('issue_docent')
    op.drop_table('news_analysis')
