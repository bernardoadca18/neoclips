"""Add semantic features to clip_candidates

Revision ID: 0007_semantic_features
Revises: 0006_discovery_hardening
Create Date: 2026-08-31

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0007_semantic_features'
down_revision = '0006_discovery_hardening'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add semantic feature columns to clip_candidates
    op.add_column('clip_candidates', sa.Column('hook_strength', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('standalone_clarity', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('narrative_completeness', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('emotional_intensity', sa.Float(), nullable=True))
    op.add_column('clip_candidates', sa.Column('topic_relevance', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('clip_candidates', 'topic_relevance')
    op.drop_column('clip_candidates', 'emotional_intensity')
    op.drop_column('clip_candidates', 'narrative_completeness')
    op.drop_column('clip_candidates', 'standalone_clarity')
    op.drop_column('clip_candidates', 'hook_strength')
