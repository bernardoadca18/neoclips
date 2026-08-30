"""NeoClips domain entities."""

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKey

if TYPE_CHECKING:
    pass


class SourcePolicy(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents a versioned utilization policy for a source.

    Controls rights, permissions, and constraints for using source content.
    """

    __tablename__ = "source_policies"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="unverified"
    )
    commercial_use_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    derivatives_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    monetization_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allowed_platforms: Mapped[list[str] | None] = mapped_column(
        ARRAY(String), nullable=True
    )
    max_clip_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attribution_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    attribution_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    embargo_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    evidence_uri: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    evidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    sources: Mapped[list["ClipSource"]] = relationship(
        "ClipSource", back_populates="source_policy"
    )

    __table_args__ = (
        CheckConstraint(
            "verification_status IN ('verified', 'unverified', 'blocked')",
            name="ck_source_policy_verification_status",
        ),
        CheckConstraint(
            "max_clip_duration_seconds IS NULL OR max_clip_duration_seconds > 0",
            name="ck_source_policy_max_duration_positive",
        ),
        CheckConstraint(
            "embargo_seconds >= 0",
            name="ck_source_policy_embargo_non_negative",
        ),
    )


class ClipSource(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents an audiovisual source known to NeoClips.

    Sources can operate in safe_automated or manual_override mode.
    """

    __tablename__ = "clip_sources"

    source_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_policies.id", ondelete="SET NULL"), nullable=True
    )
    mode: Mapped[str] = mapped_column(String(50), nullable=False)
    original_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    creator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    media_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    transcription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rights_status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="unverified"
    )
    operator_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")

    # Relationships
    source_policy: Mapped["SourcePolicy | None"] = relationship(
        "SourcePolicy", back_populates="sources"
    )
    workflows: Mapped[list["ClipWorkflow"]] = relationship(
        "ClipWorkflow", back_populates="source", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN ('safe_automated', 'manual_override')",
            name="ck_clip_source_mode",
        ),
        CheckConstraint(
            "rights_status IN ('verified', 'unverified', 'blocked')",
            name="ck_clip_source_rights_status",
        ),
        CheckConstraint(
            "status IN ('pending', 'ingesting', 'transcribing', 'ready', 'failed', 'blocked')",
            name="ck_clip_source_status",
        ),
    )


class ClipWorkflow(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents a pipeline execution for clip discovery and production.

    State is persisted in PostgreSQL, not inferred from Celery tasks.
    """

    __tablename__ = "clip_workflows"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_sources.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="created")
    current_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    source: Mapped["ClipSource"] = relationship("ClipSource", back_populates="workflows")
    error_history: Mapped[list["WorkflowErrorHistory"]] = relationship(
        "WorkflowErrorHistory", back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_clip_workflow_attempt_count",
        ),
        CheckConstraint(
            """status IN (
                'created', 'ingesting', 'transcribing', 'discovering', 'observing',
                'reranking', 'awaiting_selection', 'rendering', 'packaging', 'qa',
                'ready_for_review', 'blocked', 'failed', 'cancelled'
            )""",
            name="ck_clip_workflow_status",
        ),
    )


class WorkflowErrorHistory(Base, UUIDPrimaryKey):
    """
    Persists important failures for debugging and recovery.

    Never persists stack traces or host paths in public responses.
    """

    __tablename__ = "workflow_error_history"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_workflows.id", ondelete="CASCADE"), nullable=False
    )
    phase: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    workflow: Mapped["ClipWorkflow"] = relationship("ClipWorkflow", back_populates="error_history")

    __table_args__ = (
        CheckConstraint(
            "attempt >= 0",
            name="ck_workflow_error_history_attempt",
        ),
    )
