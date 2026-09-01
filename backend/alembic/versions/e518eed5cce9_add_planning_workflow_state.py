"""Add planning workflow state for Stage 4 editorial analysis.

Revision ID: e518eed5cce9
Revises: 0010_add_editorial_tables
Create Date: 2026-09-01

Stage 4 adds the 'planning' state between 'awaiting_selection' and 'rendering'
to support editorial suitability analysis and plan creation.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e518eed5cce9"
down_revision: str | None = "0010_add_editorial_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old constraint
    op.drop_constraint("ck_clip_workflow_status", "clip_workflows", type_="check")

    # Create new constraint with 'planning' state
    op.create_check_constraint(
        "ck_clip_workflow_status",
        "clip_workflows",
        """status IN (
            'created', 'discovering', 'observing',
            'reranking', 'awaiting_selection', 'planning', 'rendering', 'packaging', 'qa',
            'ready_for_review', 'blocked', 'failed', 'cancelled'
        )""",
    )


def downgrade() -> None:
    # Drop new constraint
    op.drop_constraint("ck_clip_workflow_status", "clip_workflows", type_="check")

    # Restore old constraint without 'planning'
    op.create_check_constraint(
        "ck_clip_workflow_status",
        "clip_workflows",
        """status IN (
            'created', 'discovering', 'observing',
            'reranking', 'awaiting_selection', 'rendering', 'packaging', 'qa',
            'ready_for_review', 'blocked', 'failed', 'cancelled'
        )""",
    )
