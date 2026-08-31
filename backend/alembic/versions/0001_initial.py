"""Initial schema with SourcePolicy, ClipSource, ClipWorkflow, WorkflowErrorHistory.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-30

"""
from typing import Sequence  # noqa: UP035

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0001_initial'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create source_policies table
    op.create_table(
        'source_policies',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('version', sa.String(50), nullable=False),
        sa.Column('verification_status', sa.String(50), nullable=False, server_default='unverified'),
        sa.Column('commercial_use_allowed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('derivatives_allowed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('monetization_allowed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('allowed_platforms', postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column('max_clip_duration_seconds', sa.Integer(), nullable=True),
        sa.Column('attribution_required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('attribution_template', sa.Text(), nullable=True),
        sa.Column('embargo_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('evidence_uri', sa.String(1024), nullable=True),
        sa.Column('evidence_note', sa.Text(), nullable=True),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("verification_status IN ('verified', 'unverified', 'blocked')", name='ck_source_policy_verification_status'),
        sa.CheckConstraint("max_clip_duration_seconds IS NULL OR max_clip_duration_seconds > 0", name='ck_source_policy_max_duration_positive'),
        sa.CheckConstraint("embargo_seconds >= 0", name='ck_source_policy_embargo_non_negative'),
    )

    # Create clip_sources table
    op.create_table(
        'clip_sources',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), primary_key=True),
        sa.Column('source_policy_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('source_policies.id', ondelete='SET NULL'), nullable=True),
        sa.Column('mode', sa.String(50), nullable=False),
        sa.Column('original_reference', sa.String(1024), nullable=True),
        sa.Column('creator', sa.String(255), nullable=True),
        sa.Column('program', sa.String(255), nullable=True),
        sa.Column('title', sa.String(500), nullable=True),
        sa.Column('media_project_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('media_session_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('media_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('transcription_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('source_sha256', sa.String(64), nullable=True),
        sa.Column('rights_status', sa.String(50), nullable=False, server_default='unverified'),
        sa.Column('operator_acknowledged', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('status', sa.String(50), nullable=False, server_default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode IN ('safe_automated', 'manual_override')", name='ck_clip_source_mode'),
        sa.CheckConstraint("rights_status IN ('verified', 'unverified', 'blocked')", name='ck_clip_source_rights_status'),
        sa.CheckConstraint("status IN ('pending', 'ingesting', 'transcribing', 'ready_for_discovery', 'ready', 'failed', 'blocked')", name='ck_clip_source_status'),
    )

    # Create clip_workflows table
    op.create_table(
        'clip_workflows',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), primary_key=True),
        sa.Column('source_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clip_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('status', sa.String(50), nullable=False, server_default='created'),
        sa.Column('current_phase', sa.String(50), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_error_category', sa.String(50), nullable=True),
        sa.Column('last_error_message', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("attempt_count >= 0", name='ck_clip_workflow_attempt_count'),
        sa.CheckConstraint(
            "status IN ('created', 'ingesting', 'transcribing', 'discovering', 'observing', 'reranking', 'awaiting_selection', 'rendering', 'packaging', 'qa', 'ready_for_review', 'blocked', 'failed', 'cancelled')",
            name='ck_clip_workflow_status'
        ),
    )

    # Create workflow_error_history table
    op.create_table(
        'workflow_error_history',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.func.gen_random_uuid(), primary_key=True),
        sa.Column('workflow_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('clip_workflows.id', ondelete='CASCADE'), nullable=False),
        sa.Column('phase', sa.String(50), nullable=False),
        sa.Column('category', sa.String(50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("attempt >= 0", name='ck_workflow_error_history_attempt'),
    )

    # Create indexes
    op.create_index('ix_source_policies_name_version', 'source_policies', ['name', 'version'], unique=True)
    op.create_index('ix_clip_sources_status', 'clip_sources', ['status'])
    op.create_index('ix_clip_sources_source_policy_id', 'clip_sources', ['source_policy_id'])
    op.create_index('ix_clip_workflows_source_id', 'clip_workflows', ['source_id'])
    op.create_index('ix_clip_workflows_status', 'clip_workflows', ['status'])
    op.create_index('ix_workflow_error_history_workflow_id', 'workflow_error_history', ['workflow_id'])


def downgrade() -> None:
    op.drop_index('ix_workflow_error_history_workflow_id', table_name='workflow_error_history')
    op.drop_index('ix_clip_workflows_status', table_name='clip_workflows')
    op.drop_index('ix_clip_workflows_source_id', table_name='clip_workflows')
    op.drop_index('ix_clip_sources_source_policy_id', table_name='clip_sources')
    op.drop_index('ix_clip_sources_status', table_name='clip_sources')
    op.drop_index('ix_source_policies_name_version', table_name='source_policies')

    op.drop_table('workflow_error_history')
    op.drop_table('clip_workflows')
    op.drop_table('clip_sources')
    op.drop_table('source_policies')
