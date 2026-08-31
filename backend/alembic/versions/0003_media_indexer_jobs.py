"""Add Media Indexer job tracking fields for durable polling.

Revision ID: 0003_media_indexer_jobs
Revises: 0002_idempotency
Create Date: 2026-08-30

"""
from typing import Sequence  # noqa: UP035

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0003_media_indexer_jobs'
down_revision: str | None = '0002_idempotency'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from sqlalchemy.dialects import postgresql

    # Add job tracking fields to clip_sources
    # These track the ProcessingJob IDs returned by Media Indexer
    op.add_column(
        'clip_sources',
        sa.Column('media_initial_job_id', postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        'clip_sources',
        sa.Column('transcription_job_id', postgresql.UUID(as_uuid=True), nullable=True),
    )

    # Add phase timestamp for durable timeout calculation
    # This allows timeout based on elapsed time, not attempt count
    op.add_column(
        'clip_sources',
        sa.Column('phase_started_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Add label field for Media Indexer session label
    op.add_column(
        'clip_sources',
        sa.Column('media_session_label', sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('clip_sources', 'media_session_label')
    op.drop_column('clip_sources', 'phase_started_at')
    op.drop_column('clip_sources', 'transcription_job_id')
    op.drop_column('clip_sources', 'media_initial_job_id')
