"""Add extended lineage fields to ClipComposition.

Revision ID: 0013_clip_composition_lineage
Revises: 0012_clip_composition_v2
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0013_clip_composition_lineage"
down_revision = "0012_clip_composition_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add extended lineage fields to ClipComposition."""
    # Add candidate_id foreign key
    op.add_column(
        "clip_compositions",
        sa.Column("candidate_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_clip_compositions_candidate_id",
        "clip_compositions",
        "clip_candidates",
        ["candidate_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_clip_compositions_candidate_id",
        "clip_compositions",
        ["candidate_id"],
    )

    # Add media_id (Media Indexer media ID - no FK, external reference)
    op.add_column(
        "clip_compositions",
        sa.Column("media_id", sa.UUID(as_uuid=True), nullable=True),
    )

    # Add transcription_id (Media Indexer transcription ID - no FK, external reference)
    op.add_column(
        "clip_compositions",
        sa.Column("transcription_id", sa.UUID(as_uuid=True), nullable=True),
    )

    # Add source_sha256 (SHA256 hash of source media file)
    op.add_column(
        "clip_compositions",
        sa.Column("source_sha256", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    """Remove extended lineage fields from ClipComposition."""
    # Drop source_sha256
    op.drop_column("clip_compositions", "source_sha256")

    # Drop transcription_id
    op.drop_column("clip_compositions", "transcription_id")

    # Drop media_id
    op.drop_column("clip_compositions", "media_id")

    # Drop candidate_id index, foreign key, and column
    op.drop_index("ix_clip_compositions_candidate_id", table_name="clip_compositions")
    op.drop_constraint("fk_clip_compositions_candidate_id", "clip_compositions", type_="foreignkey")
    op.drop_column("clip_compositions", "candidate_id")
