"""Fix ClipWorkflow status constraint to remove ingesting/transcribing.

Revision ID: 0004_fix_clip_workflow_status
Revises: 0003_media_indexer_jobs
Create Date: 2026-08-30

ClipWorkflow now only owns Clip Discovery pipeline states (discovering onwards).
ClipSource owns Media Indexer pipeline states (ingesting, transcribing).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_fix_clip_workflow_status"
down_revision: str | None = "0003_media_indexer_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop old constraint
    op.drop_constraint("ck_clip_workflow_status", "clip_workflows", type_="check")

    # Create new constraint without ingesting/transcribing
    op.create_check_constraint(
        "ck_clip_workflow_status",
        "clip_workflows",
        """status IN (
            'created', 'discovering', 'observing',
            'reranking', 'awaiting_selection', 'rendering', 'packaging', 'qa',
            'ready_for_review', 'blocked', 'failed', 'cancelled'
        )""",
    )


def downgrade() -> None:
    # Drop new constraint
    op.drop_constraint("ck_clip_workflow_status", "clip_workflows", type_="check")

    # Restore old constraint with ingesting/transcribing
    op.create_check_constraint(
        "ck_clip_workflow_status",
        "clip_workflows",
        """status IN (
            'created', 'ingesting', 'transcribing', 'discovering', 'observing',
            'reranking', 'awaiting_selection', 'rendering', 'packaging', 'qa',
            'ready_for_review', 'blocked', 'failed', 'cancelled'
        )""",
    )
