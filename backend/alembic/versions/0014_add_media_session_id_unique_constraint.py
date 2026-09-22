"""Add media_session_id unique constraint.

Revision ID: 0014_media_session_unique
Revises: e518eed5cce9
Create Date: 2026-09-21

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "0014_media_session_unique"
down_revision = "e518eed5cce9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add unique constraint to media_session_id column.

    This ensures that a Media Indexer session can only be associated
    with one ClipSource, enabling idempotent from-media-session creation.
    """
    op.create_unique_constraint(
        "uq_clip_sources_media_session_id",
        "clip_sources",
        ["media_session_id"],
    )


def downgrade() -> None:
    """Remove unique constraint from media_session_id column."""
    op.drop_constraint(
        "uq_clip_sources_media_session_id",
        "clip_sources",
        type_="unique",
    )
