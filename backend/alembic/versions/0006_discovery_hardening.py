"""Stage 2/3 hardening - add missing constraints and durable identity fields.

Revision ID: 0006_discovery_hardening
Revises: 0005_add_discovery
Create Date: 2026-08-31

This migration adds:
- UniqueConstraint for discovery_windows (run_id, window_index)
- UniqueConstraint for clip_candidates (run_id, canonical_start_seconds, canonical_end_seconds)
- Durable identity fields for discovery_runs (source_id, transcription_id, strategy_id, prompt_id, config_snapshot)
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_discovery_hardening"
down_revision: str | None = "0005_add_discovery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add durable identity fields to discovery_runs
    op.add_column(
        "discovery_runs",
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "discovery_runs",
        sa.Column("transcription_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "discovery_runs",
        sa.Column("strategy_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "discovery_runs",
        sa.Column("prompt_id", sa.String(100), nullable=True),
    )
    op.add_column(
        "discovery_runs",
        sa.Column("config_snapshot", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_discovery_runs_source_id",
        "discovery_runs",
        "clip_sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_discovery_runs_source_id", "discovery_runs", ["source_id"])

    # Add UniqueConstraint for discovery_windows (run_id, window_index)
    op.create_unique_constraint(
        "uq_discovery_window_run_index",
        "discovery_windows",
        ["run_id", "window_index"],
    )

    # Add UniqueConstraint for clip_candidates fingerprint
    op.create_unique_constraint(
        "uq_clip_candidate_fingerprint",
        "clip_candidates",
        ["run_id", "canonical_start_seconds", "canonical_end_seconds"],
    )


def downgrade() -> None:
    # Remove clip_candidates unique constraint
    op.drop_constraint("uq_clip_candidate_fingerprint", "clip_candidates", type_="unique")

    # Remove discovery_windows unique constraint
    op.drop_constraint("uq_discovery_window_run_index", "discovery_windows", type_="unique")

    # Remove discovery_runs durable identity fields
    op.drop_index("ix_discovery_runs_source_id", table_name="discovery_runs")
    op.drop_constraint("fk_discovery_runs_source_id", "discovery_runs", type_="foreignkey")
    op.drop_column("discovery_runs", "config_snapshot")
    op.drop_column("discovery_runs", "prompt_id")
    op.drop_column("discovery_runs", "strategy_id")
    op.drop_column("discovery_runs", "transcription_id")
    op.drop_column("discovery_runs", "source_id")
