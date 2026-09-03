"""NeoClips domain entities."""

import typing
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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
    compositions: Mapped[list["ClipComposition"]] = relationship(
        "ClipComposition", back_populates="workflow", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_clip_workflow_attempt_count",
        ),
        CheckConstraint(
            """status IN (
                'created', 'discovering', 'observing',
                'reranking', 'awaiting_selection', 'planning', 'rendering', 'packaging', 'qa',
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

    Durable orchestration: runs can be recovered and resumed after failures.
    """

    __tablename__ = "discovery_runs"

    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_workflows.id", ondelete="CASCADE"), nullable=False
    )
    # Durable identity fields for recovery and auditing
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_sources.id", ondelete="SET NULL"), nullable=True
    )
    transcription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Idempotency and fingerprinting
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256

    # Strategy and prompt versioning
    strategy_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategy_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256

    # Configuration snapshot (JSON)
    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    profile: Mapped[str] = mapped_column(String(50), nullable=False, server_default="transcript_only")
    llm_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Progress tracking
    total_windows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    processed_windows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_windows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_windows: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
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
            "status IN ('pending', 'running', 'completed', 'completed_with_errors', 'failed')",
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
            "completed_windows >= 0",
            name="ck_discovery_run_completed_windows",
        ),
        CheckConstraint(
            "failed_windows >= 0",
            name="ck_discovery_run_failed_windows",
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
    start_seconds: Mapped[float] = mapped_column(Float, nullable=False)  # Start time in source
    end_seconds: Mapped[float] = mapped_column(Float, nullable=False)  # End time in source
    segment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    llm_response_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_response_parsed: Mapped[dict[str, typing.Any] | None] = mapped_column(Text, nullable=True)  # JSON stored as text
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

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
        # Idempotency: ensure unique window index within a run
        UniqueConstraint("run_id", "window_index", name="uq_discovery_window_run_index"),
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
    canonical_start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    canonical_end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    hook_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hook_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Semantic features from LLM (0.0 to 1.0 scale)
    hook_strength: Mapped[float | None] = mapped_column(Float, nullable=True)
    standalone_clarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    narrative_completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    emotional_intensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    topic_relevance: Mapped[float | None] = mapped_column(Float, nullable=True)

    score_v1: Mapped[float | None] = mapped_column(Float, nullable=True)  # Deterministic score
    score_v1_components: Mapped[dict[str, typing.Any] | None] = mapped_column(Text, nullable=True)  # JSON breakdown
    candidate_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256
    discovery_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clip_candidates.id", ondelete="SET NULL"),
        nullable=True
    )
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    selection_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    run: Mapped["DiscoveryRun"] = relationship("DiscoveryRun", back_populates="candidates")
    window: Mapped["DiscoveryWindow"] = relationship("DiscoveryWindow", back_populates="candidates")
    editorial_analyses: Mapped[list["EditorialSuitabilityAnalysis"]] = relationship(
        "EditorialSuitabilityAnalysis", back_populates="candidate", cascade="all, delete-orphan"
    )
    editorial_plans: Mapped[list["ShortEditorialPlan"]] = relationship(
        "ShortEditorialPlan", back_populates="candidate", cascade="all, delete-orphan"
    )

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
        # Idempotency: unique candidate fingerprint within a run
        UniqueConstraint(
            "run_id", "candidate_fingerprint",
            name="uq_clip_candidates_fingerprint"
        ),
    )


class EditorialSuitabilityAnalysis(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents an editorial suitability analysis for a ClipCandidate.

    This is a versioned evaluation of whether a candidate works as
    standalone content, with structured output from the LLM including
    recommended editorial strategy.
    """

    __tablename__ = "editorial_suitability_analyses"

    # Core relationships
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_candidates.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_sources.id", ondelete="SET NULL"), nullable=True
    )
    transcription_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Identity and versioning
    strategy_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    strategy_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    prompt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256

    # Configuration snapshot
    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256

    # 9Router configuration
    requested_combo: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolved_model: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Context boundaries used for this analysis
    context_before_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="45.0")
    context_after_seconds: Mapped[float] = mapped_column(Float, nullable=False, server_default="40.0")

    # Status
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Analysis results (structured output from LLM)
    standalone_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    context_dependency: Mapped[str | None] = mapped_column(String(20), nullable=True)  # none, low, medium, high, critical
    hook_strength: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    payoff_strength: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    ending_completeness: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100

    # Reference dependency details
    reference_dependency_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reference_dependency_examples: Mapped[dict[str, typing.Any] | None] = mapped_column(Text, nullable=True)  # JSON

    # Editorial recommendation
    recommended_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)  # USE_DIRECTLY, TRIM, ADD_CONTEXT, REAUTHOR, REJECT
    recommended_start_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recommended_end_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    analysis_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw response for debugging
    raw_llm_response: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    # Relationships
    candidate: Mapped["ClipCandidate"] = relationship("ClipCandidate", back_populates="editorial_analyses")
    editorial_plans: Mapped[list["ShortEditorialPlan"]] = relationship(
        "ShortEditorialPlan", back_populates="analysis", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_editorial_analysis_status",
        ),
        CheckConstraint(
            "standalone_score IS NULL OR (standalone_score >= 0 AND standalone_score <= 100)",
            name="ck_editorial_analysis_standalone_score",
        ),
        CheckConstraint(
            "hook_strength IS NULL OR (hook_strength >= 0 AND hook_strength <= 100)",
            name="ck_editorial_analysis_hook_strength",
        ),
        CheckConstraint(
            "payoff_strength IS NULL OR (payoff_strength >= 0 AND payoff_strength <= 100)",
            name="ck_editorial_analysis_payoff_strength",
        ),
        CheckConstraint(
            "ending_completeness IS NULL OR (ending_completeness >= 0 AND ending_completeness <= 100)",
            name="ck_editorial_analysis_ending_completeness",
        ),
        CheckConstraint(
            "context_dependency IS NULL OR context_dependency IN ('none', 'low', 'medium', 'high', 'critical')",
            name="ck_editorial_analysis_context_dependency",
        ),
        CheckConstraint(
            "reference_dependency_level IS NULL OR reference_dependency_level IN ('none', 'low', 'medium', 'high', 'critical')",
            name="ck_editorial_analysis_reference_dependency",
        ),
        CheckConstraint(
            "recommended_strategy IS NULL OR recommended_strategy IN ('USE_DIRECTLY', 'TRIM', 'ADD_CONTEXT', 'REAUTHOR', 'REJECT')",
            name="ck_editorial_analysis_recommended_strategy",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_editorial_analysis_attempt_count",
        ),
    )


class ShortEditorialPlan(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents an editorial plan for producing a Short from a ClipCandidate.

    This is the contract between Stage 4 (Editorial) and Stage 5 (Composition).
    It captures the editorial decision and boundaries for the final clip.
    """

    __tablename__ = "short_editorial_plans"

    # Lineage - all required for provenance
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_workflows.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_sources.id", ondelete="SET NULL"), nullable=True
    )
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_candidates.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_suitability_analyses.id", ondelete="SET NULL"), nullable=True
    )

    # Editorial strategy
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    decision_source: Mapped[str] = mapped_column(String(50), nullable=False, server_default="model_recommendation")

    # Final boundaries (canonicalized from segment IDs)
    source_start_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_end_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source_end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    # Human override tracking
    recommended_strategy: Mapped[str | None] = mapped_column(String(50), nullable=True)
    recommended_start_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recommended_end_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Rejection reason (for REJECT strategy)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Plan status
    status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="draft")

    # Versioning and fingerprint
    plan_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    config_snapshot: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA-256

    # Relationships
    candidate: Mapped["ClipCandidate"] = relationship("ClipCandidate", back_populates="editorial_plans")
    analysis: Mapped["EditorialSuitabilityAnalysis | None"] = relationship(
        "EditorialSuitabilityAnalysis", back_populates="editorial_plans"
    )
    compositions: Mapped[list["ClipComposition"]] = relationship(
        "ClipComposition", back_populates="plan", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(
            "strategy IN ('USE_DIRECTLY', 'TRIM', 'ADD_CONTEXT', 'REAUTHOR', 'REJECT')",
            name="ck_short_editorial_plan_strategy",
        ),
        CheckConstraint(
            "decision_source IN ('model_recommendation', 'human_override')",
            name="ck_short_editorial_plan_decision_source",
        ),
        CheckConstraint(
            "status IN ('draft', 'ready', 'rejected', 'invalidated')",
            name="ck_short_editorial_plan_status",
        ),
        CheckConstraint(
            "source_start_seconds >= 0",
            name="ck_short_editorial_plan_start",
        ),
        CheckConstraint(
            "source_end_seconds > source_start_seconds",
            name="ck_short_editorial_plan_end_after_start",
        ),
        CheckConstraint(
            "duration_seconds > 0",
            name="ck_short_editorial_plan_duration_positive",
        ),
    )


class ClipComposition(Base, UUIDPrimaryKey, TimestampMixin):
    """
    Represents the composition contract for producing a Short.

    This is the Stage 5 entity that bridges editorial plans (Stage 4)
    and rendering (Stage 6). It captures:
    - Source material boundaries (from plan)
    - Render profile (vertical_short_v1)
    - Audio/caption modes for rendering
    - Fingerprint for idempotency

    V2 Changes:
    - Removed composition_params (editorial params belong in analysis)
    - Added analysis_id for full lineage
    - Added composition_version for schema evolution
    - Added audio_mode and caption_mode for render configuration
    """

    __tablename__ = "clip_compositions"

    # Lineage - full provenance chain
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_workflows.id", ondelete="CASCADE"), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clip_sources.id", ondelete="SET NULL"), nullable=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("short_editorial_plans.id", ondelete="CASCADE"), nullable=False
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_suitability_analyses.id", ondelete="SET NULL"), nullable=True
    )

    # Composition version for schema evolution
    composition_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="2")

    # Source boundaries (from plan)
    source_start_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    source_end_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(Float, nullable=False)

    # Segment IDs for traceability (from plan)
    source_start_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    source_end_segment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Editorial strategy (from plan)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)

    # Render profile - versioned for reproducibility
    render_profile: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="vertical_short_v1"
    )

    # Audio mode for rendering
    audio_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="original"
    )

    # Caption mode for rendering
    caption_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="none"
    )

    # Status
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="pending"
    )

    # Render output (populated after rendering)
    render_job_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    output_media_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Fingerprint for idempotency
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Relationships
    workflow: Mapped["ClipWorkflow"] = relationship("ClipWorkflow", back_populates="compositions")
    plan: Mapped["ShortEditorialPlan"] = relationship("ShortEditorialPlan", back_populates="compositions")
    analysis: Mapped["EditorialSuitabilityAnalysis"] = relationship(
        "EditorialSuitabilityAnalysis", back_populates="compositions"
    )

    __table_args__ = (
        CheckConstraint(
            """strategy IN ('USE_DIRECTLY', 'TRIM', 'ADD_CONTEXT')""",
            name="ck_clip_composition_strategy",
        ),
        CheckConstraint(
            "source_start_seconds >= 0",
            name="ck_clip_composition_start",
        ),
        CheckConstraint(
            "source_end_seconds > source_start_seconds",
            name="ck_clip_composition_end_after_start",
        ),
        CheckConstraint(
            "duration_seconds > 0",
            name="ck_clip_composition_duration_positive",
        ),
        CheckConstraint(
            """status IN ('pending', 'validating', 'ready', 'rendering', 'completed', 'failed')""",
            name="ck_clip_composition_status",
        ),
        CheckConstraint(
            """audio_mode IN ('original', 'mixed', 'replaced')""",
            name="ck_clip_composition_audio_mode",
        ),
        CheckConstraint(
            """caption_mode IN ('none', 'burned', 'sidecar')""",
            name="ck_clip_composition_caption_mode",
        ),
        CheckConstraint(
            "composition_version >= 1",
            name="ck_clip_composition_version",
        ),
    )
