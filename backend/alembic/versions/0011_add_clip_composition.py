"""Add ClipComposition table for Stage 5.

Revision ID: 0011_add_clip_composition
Revises: 0010_add_editorial_tables
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0011_add_clip_composition"
down_revision = "e518eed5cce9"  # Chain after planning state migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create clip_compositions table."""
    op.create_table(
        "clip_compositions",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("workflow_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("plan_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("source_start_seconds", sa.Float(), nullable=False),
        sa.Column("source_end_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("source_start_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("source_end_segment_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column(
            "render_profile",
            sa.String(50),
            nullable=False,
            server_default="vertical_short_v1",
        ),
        sa.Column(
            "composition_params",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("render_job_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("output_media_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id"],
            ["clip_workflows.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["clip_sources.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"],
            ["short_editorial_plans.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
        sa.CheckConstraint(
            "strategy IN ('USE_DIRECTLY', 'TRIM', 'ADD_CONTEXT')",
            name="ck_clip_composition_strategy",
        ),
        sa.CheckConstraint(
            "source_start_seconds >= 0",
            name="ck_clip_composition_start",
        ),
        sa.CheckConstraint(
            "source_end_seconds > source_start_seconds",
            name="ck_clip_composition_end_after_start",
        ),
        sa.CheckConstraint(
            "duration_seconds > 0",
            name="ck_clip_composition_duration_positive",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'validating', 'ready', 'rendering', 'completed', 'failed')",
            name="ck_clip_composition_status",
        ),
    )

    # Add indexes for common queries
    op.create_index(
        "ix_clip_compositions_workflow_id",
        "clip_compositions",
        ["workflow_id"],
    )
    op.create_index(
        "ix_clip_compositions_plan_id",
        "clip_compositions",
        ["plan_id"],
    )
    op.create_index(
        "ix_clip_compositions_status",
        "clip_compositions",
        ["status"],
    )


def downgrade() -> None:
    """Remove clip_compositions table."""
    op.drop_index("ix_clip_compositions_status", table_name="clip_compositions")
    op.drop_index("ix_clip_compositions_plan_id", table_name="clip_compositions")
    op.drop_index("ix_clip_compositions_workflow_id", table_name="clip_compositions")
    op.drop_table("clip_compositions")
