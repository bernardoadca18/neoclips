"""Add Stage 4 editorial entities.

Revision ID: 0010_add_editorial_tables
Revises: 0009_discovery_run_completed_with_errors
Create Date: 2026-09-01

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_add_editorial_tables"
down_revision: str | None = "0009_discovery_run_completed_with_errors"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Create editorial_suitability_analyses table
    op.create_table(
        "editorial_suitability_analyses",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        # Core relationships
        sa.Column("candidate_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("transcription_id", sa.UUID(as_uuid=True), nullable=True),
        # Identity and versioning
        sa.Column("strategy_id", sa.String(100), nullable=True),
        sa.Column("strategy_version", sa.String(50), nullable=True),
        sa.Column("prompt_id", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("prompt_hash", sa.String(64), nullable=True),
        # Configuration snapshot
        sa.Column("config_snapshot", sa.Text(), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=True),
        # 9Router configuration
        sa.Column("requested_combo", sa.String(100), nullable=True),
        sa.Column("resolved_model", sa.String(100), nullable=True),
        # Context boundaries
        sa.Column("context_before_seconds", sa.Float(), nullable=False, server_default="45.0"),
        sa.Column("context_after_seconds", sa.Float(), nullable=False, server_default="40.0"),
        # Status
        sa.Column("status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        # Analysis results
        sa.Column("standalone_score", sa.Integer(), nullable=True),
        sa.Column("context_dependency", sa.String(20), nullable=True),
        sa.Column("hook_strength", sa.Integer(), nullable=True),
        sa.Column("payoff_strength", sa.Integer(), nullable=True),
        sa.Column("ending_completeness", sa.Integer(), nullable=True),
        # Reference dependency details
        sa.Column("reference_dependency_level", sa.String(20), nullable=True),
        sa.Column("reference_dependency_examples", sa.Text(), nullable=True),
        # Editorial recommendation
        sa.Column("recommended_strategy", sa.String(50), nullable=True),
        sa.Column("recommended_start_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("recommended_end_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("analysis_summary", sa.Text(), nullable=True),
        # Raw response
        sa.Column("raw_llm_response", sa.Text(), nullable=True),
        # Timing
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Check constraints
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_editorial_analysis_status",
        ),
        sa.CheckConstraint(
            "standalone_score IS NULL OR (standalone_score >= 0 AND standalone_score <= 100)",
            name="ck_editorial_analysis_standalone_score",
        ),
        sa.CheckConstraint(
            "hook_strength IS NULL OR (hook_strength >= 0 AND hook_strength <= 100)",
            name="ck_editorial_analysis_hook_strength",
        ),
        sa.CheckConstraint(
            "payoff_strength IS NULL OR (payoff_strength >= 0 AND payoff_strength <= 100)",
            name="ck_editorial_analysis_payoff_strength",
        ),
        sa.CheckConstraint(
            "ending_completeness IS NULL OR (ending_completeness >= 0 AND ending_completeness <= 100)",
            name="ck_editorial_analysis_ending_completeness",
        ),
        sa.CheckConstraint(
            "context_dependency IS NULL OR context_dependency IN ('none', 'low', 'medium', 'high', 'critical')",
            name="ck_editorial_analysis_context_dependency",
        ),
        sa.CheckConstraint(
            "reference_dependency_level IS NULL OR reference_dependency_level IN ('none', 'low', 'medium', 'high', 'critical')",
            name="ck_editorial_analysis_reference_dependency",
        ),
        sa.CheckConstraint(
            "recommended_strategy IS NULL OR recommended_strategy IN ('USE_DIRECTLY', 'TRIM', 'ADD_CONTEXT', 'REAUTHOR', 'REJECT')",
            name="ck_editorial_analysis_recommended_strategy",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_editorial_analysis_attempt_count",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["candidate_id"], ["clip_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["clip_sources.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_editorial_analyses_candidate_id", "editorial_suitability_analyses", ["candidate_id"])
    op.create_index("ix_editorial_analyses_source_id", "editorial_suitability_analyses", ["source_id"])

    # Create short_editorial_plans table
    op.create_table(
        "short_editorial_plans",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        # Lineage
        sa.Column("workflow_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("analysis_id", sa.UUID(as_uuid=True), nullable=True),
        # Editorial strategy
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("decision_source", sa.String(50), nullable=False, server_default="model_recommendation"),
        # Final boundaries
        sa.Column("source_start_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("source_end_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("source_start_seconds", sa.Float(), nullable=False),
        sa.Column("source_end_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        # Human override tracking
        sa.Column("recommended_strategy", sa.String(50), nullable=True),
        sa.Column("recommended_start_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("recommended_end_segment_id", sa.UUID(as_uuid=True), nullable=True),
        # Rejection reason
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        # Plan status
        sa.Column("status", sa.String(50), nullable=False, server_default="draft"),
        # Versioning and fingerprint
        sa.Column("plan_version", sa.String(50), nullable=True),
        sa.Column("config_snapshot", sa.Text(), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        # Check constraints
        sa.CheckConstraint(
            "strategy IN ('USE_DIRECTLY', 'TRIM', 'ADD_CONTEXT', 'REAUTHOR', 'REJECT')",
            name="ck_short_editorial_plan_strategy",
        ),
        sa.CheckConstraint(
            "decision_source IN ('model_recommendation', 'human_override')",
            name="ck_short_editorial_plan_decision_source",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'ready', 'rejected', 'invalidated')",
            name="ck_short_editorial_plan_status",
        ),
        sa.CheckConstraint(
            "source_start_seconds >= 0",
            name="ck_short_editorial_plan_start",
        ),
        sa.CheckConstraint(
            "source_end_seconds > source_start_seconds",
            name="ck_short_editorial_plan_end_after_start",
        ),
        sa.CheckConstraint(
            "duration_seconds > 0",
            name="ck_short_editorial_plan_duration_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["workflow_id"], ["clip_workflows.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["clip_sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["candidate_id"], ["clip_candidates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["analysis_id"], ["editorial_suitability_analyses.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_editorial_plans_workflow_id", "short_editorial_plans", ["workflow_id"])
    op.create_index("ix_editorial_plans_candidate_id", "short_editorial_plans", ["candidate_id"])
    op.create_index("ix_editorial_plans_analysis_id", "short_editorial_plans", ["analysis_id"])


def downgrade() -> None:
    op.drop_index("ix_editorial_plans_analysis_id", table_name="short_editorial_plans")
    op.drop_index("ix_editorial_plans_candidate_id", table_name="short_editorial_plans")
    op.drop_index("ix_editorial_plans_workflow_id", table_name="short_editorial_plans")
    op.drop_table("short_editorial_plans")

    op.drop_index("ix_editorial_analyses_source_id", table_name="editorial_suitability_analyses")
    op.drop_index("ix_editorial_analyses_candidate_id", table_name="editorial_suitability_analyses")
    op.drop_table("editorial_suitability_analyses")
