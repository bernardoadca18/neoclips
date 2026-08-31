"""Add idempotency fields and unique constraint for workflows.

Revision ID: 0002_idempotency
Revises: 0001_initial
Create Date: 2026-08-30

"""
from typing import Sequence  # noqa: UP035

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0002_idempotency'
down_revision: str | None = '0001_initial'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add idempotency fields to clip_sources
    op.add_column('clip_sources', sa.Column('idempotency_key', sa.String(64), nullable=True))
    op.add_column('clip_sources', sa.Column('request_fingerprint', sa.String(64), nullable=True))
    op.create_index('ix_clip_sources_idempotency_key', 'clip_sources', ['idempotency_key'])

    # Add idempotency fields to clip_workflows
    op.add_column('clip_workflows', sa.Column('idempotency_key', sa.String(64), nullable=True))
    op.add_column('clip_workflows', sa.Column('request_fingerprint', sa.String(64), nullable=True))
    op.create_index('ix_clip_workflows_idempotency_key', 'clip_workflows', ['idempotency_key'])

    # Make source_id unique in clip_workflows (one workflow per source)
    op.drop_index('ix_clip_workflows_source_id', table_name='clip_workflows')
    op.create_unique_constraint('uq_clip_workflows_source_id', 'clip_workflows', ['source_id'])


def downgrade() -> None:
    # Revert unique constraint on clip_workflows.source_id
    op.drop_constraint('uq_clip_workflows_source_id', 'clip_workflows', type_='unique')
    op.create_index('ix_clip_workflows_source_id', 'clip_workflows', ['source_id'])

    # Remove idempotency fields from clip_workflows
    op.drop_index('ix_clip_workflows_idempotency_key', table_name='clip_workflows')
    op.drop_column('clip_workflows', 'request_fingerprint')
    op.drop_column('clip_workflows', 'idempotency_key')

    # Remove idempotency fields from clip_sources
    op.drop_index('ix_clip_sources_idempotency_key', table_name='clip_sources')
    op.drop_column('clip_sources', 'request_fingerprint')
    op.drop_column('clip_sources', 'idempotency_key')
