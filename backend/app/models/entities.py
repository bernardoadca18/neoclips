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
    Name and version are immutable after creation.
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
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    original_reference: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    creator: Mapped[str | None] = mapped_column(String(255), nullable=True)
    program: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    media_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    media_session_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    media_initial_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    transcription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    transcription_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    phase_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
            "status IN ('pending', 'ingesting', 'transcribing', 'ready_for_discovery', 'ready', 'failed', 'blocked')",
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
        UUID(as_uuid=True), ForeignKey("clip_sources.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="created")
    current_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Relationships
    source: Mapped["ClipSource"] = relationship("ClipSource", back_populates="workflows")
    error_history: Mapped[list["WorkflowErrorHistory"]] = relationship(
        "WorkflowErrorHistory", back_populates="workflow", cascade="all, delete-orphan"
    )
    discovery_runs: Mapped[list["DiscoveryRun"]] = relationship(
        "DiscoveryRun", back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_clip_workflow_attempt_count",
        ),
        CheckConstraint(
            """status IN (
                'created', 'discovering', 'observing',
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


class DiscoveryRun(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents a clip discovery execution for a workflow.

    Each workflow can have multiple discovery runs (e.g., after reranking).
    A run processes transcript windows and produces clip candidates.
    """

    __tablename__ = "discovery_runs"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_workflows.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    profile: Mapped[str] = mapped_column(String(50), nullable=False, server_default="transcript_only")
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_windows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    processed_windows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    total_candidates: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    workflow: Mapped["ClipWorkflow"] = relationship("ClipWorkflow", back_populates="discovery_runs")
    windows: Mapped[list["DiscoveryWindow"]] = relationship(
        "DiscoveryWindow", back_populates="run", cascade="all, delete-orphan"
    )
    candidates: Mapped[list["ClipCandidate"]] = relationship(
        "ClipCandidate", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_discovery_run_status",
        ),
        CheckConstraint(
            "profile IN ('transcript_only', 'transcript_plus_visual', 'full_multimodal')",
            name="ck_discovery_run_profile",
        ),
        CheckConstraint(
            "total_windows >= 0",
            name="ck_discovery_run_total_windows",
        ),
        CheckConstraint(
            "processed_windows >= 0",
            name="ck_discovery_run_processed_windows",
        ),
        CheckConstraint(
            "total_candidates >= 0",
            name="ck_discovery_run_total_candidates",
        ),
    )


class DiscoveryWindow(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents a bounded transcript segment for LLM processing.

    Windows are created by TranscriptWindowBuilder with configurable
    overlap to ensure clip candidates spanning window boundaries are captured.
    """

    __tablename__ = "discovery_windows"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False
    )
    window_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_seconds: Mapped[float] = mapped_column(Integer, nullable=False)  # Start time in source
    end_seconds: Mapped[float] = mapped_column(Integer, nullable=False)  # End time in source
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    llm_response_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_response_parsed: Mapped[dict | None] = mapped_column(Text, nullable=True)  # JSON stored as text
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    run: Mapped["DiscoveryRun"] = relationship("DiscoveryRun", back_populates="windows")
    candidates: Mapped[list["ClipCandidate"]] = relationship(
        "ClipCandidate", back_populates="window", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_discovery_window_status",
        ),
        CheckConstraint(
            "window_index >= 0",
            name="ck_discovery_window_index",
        ),
        CheckConstraint(
            "start_seconds >= 0",
            name="ck_discovery_window_start",
        ),
        CheckConstraint(
            "end_seconds > start_seconds",
            name="ck_discovery_window_end_after_start",
        ),
        CheckConstraint(
            "segment_count >= 0",
            name="ck_discovery_window_segment_count",
        ),
    )


class ClipCandidate(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents a potential clip discovered by the LLM.

    The LLM returns segment IDs; the CandidateCanonicalizer resolves them
    to trusted timestamps from the transcript. Scoring is deterministic
    and reproducible.
    """

    __tablename__ = "clip_candidates"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False
    )
    window_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("discovery_windows.id", ondelete="CASCADE"), nullable=False
    )
    llm_suggested_start_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    llm_suggested_end_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    canonical_start_seconds: Mapped[float] = mapped_column(Integer, nullable=False)
    canonical_end_seconds: Mapped[float] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Integer, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hook_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    score_v1: Mapped[float | None] = mapped_column(Integer, nullable=True)  # Deterministic score
    score_v1_components: Mapped[dict | None] = mapped_column(Text, nullable=True)  # JSON breakdown
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    selection_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    run: Mapped["DiscoveryRun"] = relationship("DiscoveryRun", back_populates="candidates")
    window: Mapped["DiscoveryWindow"] = relationship("DiscoveryWindow", back_populates="candidates")

    __table_args__ = (
        CheckConstraint(
            "canonical_start_seconds >= 0",
            name="ck_clip_candidate_start",
        ),
        CheckConstraint(
            "canonical_end_seconds > canonical_start_seconds",
            name="ck_clip_candidate_end_after_start",
        ),
        CheckConstraint(
            "duration_seconds > 0",
            name="ck_clip_candidate_duration_positive",
        ),
        CheckConstraint(
            "score_v1 IS NULL OR (score_v1 >= 0 AND score_v1 <= 100)",
            name="ck_clip_candidate_score_range",
        ),
        CheckConstraint(
            "selection_rank IS NULL OR selection_rank >= 1",
            name="ck_clip_candidate_selection_rank",
        ),
    )
