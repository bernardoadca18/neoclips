"""Upgrade ClipComposition to V2 schema.

Revision ID: 0012_clip_composition_v2
Revises: 0011_add_clip_composition
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0012_clip_composition_v2"
down_revision = "0011_add_clip_composition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Upgrade ClipComposition to V2 schema."""
    # Add new lineage field
    op.add_column(
        "clip_compositions",
        sa.Column("analysis_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_clip_compositions_analysis_id",
        "clip_compositions",
        "editorial_suitability_analyses",
        ["analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_clip_compositions_analysis_id",
        "clip_compositions",
        ["analysis_id"],
    )

    # Add composition version
    op.add_column(
        "clip_compositions",
        sa.Column(
            "composition_version",
            sa.Integer(),
            nullable=False,
            server_default="2",
        ),
    )

    # Add audio_mode
    op.add_column(
        "clip_compositions",
        sa.Column(
            "audio_mode",
            sa.String(20),
            nullable=False,
            server_default="original",
        ),
    )

    # Add caption_mode
    op.add_column(
        "clip_compositions",
        sa.Column(
            "caption_mode",
            sa.String(20),
            nullable=False,
            server_default="none",
        ),
    )

    # Add check constraints for new fields
    op.create_check_constraint(
        "ck_clip_composition_audio_mode",
        "clip_compositions",
        "audio_mode IN ('original', 'mixed', 'replaced')",
    )
    op.create_check_constraint(
        "ck_clip_composition_caption_mode",
        "clip_compositions",
        "caption_mode IN ('none', 'burned', 'sidecar')",
    )
    op.create_check_constraint(
        "ck_clip_composition_version",
        "clip_compositions",
        "composition_version >= 1",
    )

    # Drop composition_params column (editorial params belong in analysis)
    op.drop_column("clip_compositions", "composition_params")


def downgrade() -> None:
    """Downgrade ClipComposition to V1 schema."""
    # Re-add composition_params
    op.add_column(
        "clip_compositions",
        sa.Column(
            "composition_params",
            sa.dialects.postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )

    # Drop check constraints
    op.drop_constraint("ck_clip_composition_version", "clip_compositions", type_="check")
    op.drop_constraint("ck_clip_composition_caption_mode", "clip_compositions", type_="check")
    op.drop_constraint("ck_clip_composition_audio_mode", "clip_compositions", type_="check")

    # Drop new columns
    op.drop_column("clip_compositions", "caption_mode")
    op.drop_column("clip_compositions", "audio_mode")
    op.drop_column("clip_compositions", "composition_version")

    # Drop analysis_id index and foreign key
    op.drop_index("ix_clip_compositions_analysis_id", table_name="clip_compositions")
    op.drop_constraint("fk_clip_compositions_analysis_id", "clip_compositions", type_="foreignkey")
    op.drop_column("clip_compositions", "analysis_id")
