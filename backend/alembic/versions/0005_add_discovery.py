"""Add Stage 3 discovery entities.

Revision ID: 0005_add_discovery
Revises: 0004_fix_clip_workflow_status
Create Date: 2026-08-30

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_add_discovery"
down_revision: str | None = "0004_fix_clip_workflow_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create discovery_runs table
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("profile", sa.String(50), nullable=False, server_default="transcript_only"),
        sa.Column("llm_model", sa.String(100), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("total_windows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_windows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_discovery_run_status",
        ),
        sa.CheckConstraint(
            "profile IN ('transcript_only', 'transcript_plus_visual', 'full_multimodal')",
            name="ck_discovery_run_profile",
        ),
        sa.CheckConstraint("total_windows >= 0", name="ck_discovery_run_total_windows"),
        sa.CheckConstraint("processed_windows >= 0", name="ck_discovery_run_processed_windows"),
        sa.CheckConstraint("total_candidates >= 0", name="ck_discovery_run_total_candidates"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_id"], ["clip_workflows.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_discovery_runs_workflow_id", "discovery_runs", ["workflow_id"])

    # Create discovery_windows table
    op.create_table(
        "discovery_windows",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("window_index", sa.Integer(), nullable=False),
        sa.Column("start_seconds", sa.Float(), nullable=False),
        sa.Column("end_seconds", sa.Float(), nullable=False),
        sa.Column("segment_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("llm_response_raw", sa.Text(), nullable=True),
        sa.Column("llm_response_parsed", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_discovery_window_status",
        ),
        sa.CheckConstraint("window_index >= 0", name="ck_discovery_window_index"),
        sa.CheckConstraint("start_seconds >= 0", name="ck_discovery_window_start"),
        sa.CheckConstraint("end_seconds > start_seconds", name="ck_discovery_window_end_after_start"),
        sa.CheckConstraint("segment_count >= 0", name="ck_discovery_window_segment_count"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_discovery_windows_run_id", "discovery_windows", ["run_id"])

    # Create clip_candidates table
    op.create_table(
        "clip_candidates",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("window_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("llm_suggested_start_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("llm_suggested_end_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("canonical_start_seconds", sa.Float(), nullable=False),
        sa.Column("canonical_end_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("hook_type", sa.String(50), nullable=True),
        sa.Column("hook_description", sa.Text(), nullable=True),
        sa.Column("score_v1", sa.Float(), nullable=True),
        sa.Column("score_v1_components", sa.Text(), nullable=True),
        sa.Column("is_duplicate", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("duplicate_of_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("selection_rank", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("canonical_start_seconds >= 0", name="ck_clip_candidate_start"),
        sa.CheckConstraint("canonical_end_seconds > canonical_start_seconds", name="ck_clip_candidate_end_after_start"),
        sa.CheckConstraint("duration_seconds > 0", name="ck_clip_candidate_duration_positive"),
        sa.CheckConstraint(
            "score_v1 IS NULL OR (score_v1 >= 0 AND score_v1 <= 100)",
            name="ck_clip_candidate_score_range",
        ),
        sa.CheckConstraint(
            "selection_rank IS NULL OR selection_rank >= 1",
            name="ck_clip_candidate_selection_rank",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["discovery_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["window_id"], ["discovery_windows.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_clip_candidates_run_id", "clip_candidates", ["run_id"])
    op.create_index("ix_clip_candidates_window_id", "clip_candidates", ["window_id"])


def downgrade() -> None:
    op.drop_index("ix_clip_candidates_window_id", table_name="clip_candidates")
    op.drop_index("ix_clip_candidates_run_id", table_name="clip_candidates")
    op.drop_table("clip_candidates")

    op.drop_index("ix_discovery_windows_run_id", table_name="discovery_windows")
    op.drop_table("discovery_windows")

    op.drop_index("ix_discovery_runs_workflow_id", table_name="discovery_runs")
    op.drop_table("discovery_runs")
