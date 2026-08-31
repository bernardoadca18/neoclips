"""Add durable orchestration fields

Revision ID: 0008_durable_orchestration
Revises: 0007_semantic_features
Create Date: 2026-08-31

This migration adds fields required for durable, restartable discovery orchestration:
- DiscoveryRun: idempotency, fingerprinting, tracking
- DiscoveryWindow: processing timestamps, attempt counting
- ClipCandidate: SHA-256 fingerprint, discovery rank
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0008_durable_orchestration'
down_revision = '0007_semantic_features'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # === DiscoveryRun: Durable identity and idempotency fields ===
    op.add_column('discovery_runs', sa.Column('idempotency_key', sa.String(255), nullable=True))
    op.add_column('discovery_runs', sa.Column('request_fingerprint', sa.String(64), nullable=True))
    op.add_column('discovery_runs', sa.Column('strategy_version', sa.String(50), nullable=True))
    op.add_column('discovery_runs', sa.Column('prompt_version', sa.String(50), nullable=True))
    op.add_column('discovery_runs', sa.Column('prompt_hash', sa.String(64), nullable=True))
    op.add_column('discovery_runs', sa.Column('completed_windows', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('discovery_runs', sa.Column('failed_windows', sa.Integer(), nullable=False, server_default='0'))

    # Index for idempotency lookups
    op.create_index('ix_discovery_runs_idempotency_key', 'discovery_runs', ['idempotency_key'], unique=False)
    op.create_index('ix_discovery_runs_request_fingerprint', 'discovery_runs', ['request_fingerprint'], unique=False)

    # Unique constraint on idempotency_key (one active run per key)
    op.create_unique_constraint('uq_discovery_runs_idempotency_key', 'discovery_runs', ['idempotency_key'])

    # === DiscoveryWindow: Processing timestamps and attempt counting ===
    op.add_column('discovery_windows', sa.Column('processing_started_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('discovery_windows', sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'))

    # === ClipCandidate: SHA-256 fingerprint and discovery rank ===
    op.add_column('clip_candidates', sa.Column('candidate_fingerprint', sa.String(64), nullable=True))
    op.add_column('clip_candidates', sa.Column('discovery_rank', sa.Integer(), nullable=True))

    # Index for fingerprint lookups
    op.create_index('ix_clip_candidates_fingerprint', 'clip_candidates', ['candidate_fingerprint'], unique=False)

    # Drop the old misleading float-based unique constraint
    op.drop_constraint('uq_clip_candidate_fingerprint', 'clip_candidates', type_='unique')

    # Create new fingerprint-based unique constraint
    op.create_unique_constraint('uq_clip_candidates_fingerprint', 'clip_candidates', ['run_id', 'candidate_fingerprint'])

    # Add FK for duplicate_of_id self-reference
    op.create_foreign_key(
        'fk_clip_candidates_duplicate_of_id',
        'clip_candidates',
        'clip_candidates',
        ['duplicate_of_id'],
        ['id'],
        ondelete='SET NULL'
    )


def downgrade() -> None:
    # ClipCandidate
    op.drop_constraint('fk_clip_candidates_duplicate_of_id', 'clip_candidates', type_='foreignkey')
    op.drop_constraint('uq_clip_candidates_fingerprint', 'clip_candidates', type_='unique')
    op.drop_index('ix_clip_candidates_fingerprint', 'clip_candidates')
    op.drop_column('clip_candidates', 'discovery_rank')
    op.drop_column('clip_candidates', 'candidate_fingerprint')
    # Restore old constraint
    op.create_unique_constraint(
        'uq_clip_candidate_fingerprint',
        'clip_candidates',
        ['run_id', 'canonical_start_seconds', 'canonical_end_seconds']
    )

    # DiscoveryWindow
    op.drop_column('discovery_windows', 'attempt_count')
    op.drop_column('discovery_windows', 'processing_started_at')

    # DiscoveryRun
    op.drop_constraint('uq_discovery_runs_idempotency_key', 'discovery_runs', type_='unique')
    op.drop_index('ix_discovery_runs_request_fingerprint', 'discovery_runs')
    op.drop_index('ix_discovery_runs_idempotency_key', 'discovery_runs')
    op.drop_column('discovery_runs', 'failed_windows')
    op.drop_column('discovery_runs', 'completed_windows')
    op.drop_column('discovery_runs', 'prompt_hash')
    op.drop_column('discovery_runs', 'prompt_version')
    op.drop_column('discovery_runs', 'strategy_version')
    op.drop_column('discovery_runs', 'request_fingerprint')
    op.drop_column('discovery_runs', 'idempotency_key')
