"""Pydantic schemas for Discovery Run, Window, and Clip Candidate."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class DiscoveryRunBase(BaseModel):
    """Base schema for DiscoveryRun."""

    profile: str = Field(default="transcript_only", description="Discovery profile")


class DiscoveryRunCreate(DiscoveryRunBase):
    """Schema for creating a DiscoveryRun."""

    workflow_id: UUID = Field(..., description="Workflow ID")


class DiscoveryRunUpdate(BaseModel):
    """Schema for updating a DiscoveryRun."""

    status: str | None = None
    total_windows: int | None = None
    processed_windows: int | None = None
    total_candidates: int | None = None
    error_message: str | None = None
    completed_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"pending", "running", "completed", "failed"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v


class DiscoveryRunRead(BaseModel):
    """Schema for reading a DiscoveryRun."""

    id: UUID
    workflow_id: UUID
    status: str
    profile: str
    llm_model: str | None
    llm_provider: str | None
    total_windows: int
    processed_windows: int
    completed_windows: int
    failed_windows: int
    total_candidates: int
    idempotency_key: str | None
    request_fingerprint: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DiscoveryWindowBase(BaseModel):
    """Base schema for DiscoveryWindow."""

    window_index: int = Field(..., ge=0)
    start_seconds: float = Field(..., ge=0)
    end_seconds: float = Field(...)


class DiscoveryWindowCreate(DiscoveryWindowBase):
    """Schema for creating a DiscoveryWindow."""

    run_id: UUID
    segment_count: int = Field(default=0, ge=0)


class DiscoveryWindowUpdate(BaseModel):
    """Schema for updating a DiscoveryWindow."""

    status: str | None = None
    llm_response_raw: str | None = None
    llm_response_parsed: dict | None = None
    error_message: str | None = None
    processed_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"pending", "processing", "completed", "failed"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v


class DiscoveryWindowRead(BaseModel):
    """Schema for reading a DiscoveryWindow."""

    id: UUID
    run_id: UUID
    window_index: int
    start_seconds: float
    end_seconds: float
    segment_count: int
    status: str
    attempt_count: int
    error_message: str | None
    processed_at: datetime | None
    processing_started_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ClipCandidateBase(BaseModel):
    """Base schema for ClipCandidate."""

    canonical_start_seconds: float = Field(..., ge=0)
    canonical_end_seconds: float = Field(...)
    duration_seconds: float = Field(..., gt=0)


class ClipCandidateCreate(ClipCandidateBase):
    """Schema for creating a ClipCandidate."""

    run_id: UUID
    window_id: UUID
    llm_suggested_start_segment_id: UUID | None = None
    llm_suggested_end_segment_id: UUID | None = None
    title: str | None = None
    summary: str | None = None
    hook_type: str | None = None
    hook_description: str | None = None


class ClipCandidateUpdate(BaseModel):
    """Schema for updating a ClipCandidate."""

    score_v1: float | None = None
    score_v1_components: dict | None = None
    is_duplicate: bool | None = None
    duplicate_of_id: UUID | None = None
    selected: bool | None = None
    selection_rank: int | None = None

    @field_validator("score_v1")
    @classmethod
    def validate_score(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not (0 <= v <= 100):
            raise ValueError("score_v1 must be between 0 and 100")
        return v

    @field_validator("selection_rank")
    @classmethod
    def validate_rank(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if v < 1:
            raise ValueError("selection_rank must be >= 1")
        return v


class ClipCandidateRead(BaseModel):
    """Schema for reading a ClipCandidate."""

    id: UUID
    run_id: UUID
    window_id: UUID
    llm_suggested_start_segment_id: UUID | None
    llm_suggested_end_segment_id: UUID | None
    canonical_start_seconds: float
    canonical_end_seconds: float
    duration_seconds: float
    title: str | None
    summary: str | None
    hook_type: str | None
    hook_description: str | None
    hook_strength: float | None
    standalone_clarity: float | None
    narrative_completeness: float | None
    emotional_intensity: float | None
    topic_relevance: float | None
    score_v1: float | None
    score_v1_components: dict | None
    candidate_fingerprint: str | None
    discovery_rank: int | None
    is_duplicate: bool
    duplicate_of_id: UUID | None
    selected: bool
    selection_rank: int | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# LLM Response schemas for ClipDiscoveryProvider


class LLMClipSuggestion(BaseModel):
    """A single clip suggestion from the LLM with semantic features."""

    start_segment_id: UUID = Field(..., description="ID of the starting transcript segment")
    end_segment_id: UUID = Field(..., description="ID of the ending transcript segment")
    title: str = Field(..., min_length=1, max_length=255)
    summary: str = Field(..., min_length=1)
    hook_type: str = Field(..., description="Type of hook (e.g., 'question', 'statement', 'story')")
    hook_description: str = Field(..., description="Why this makes a good clip")

    # Semantic features for scoring (0.0 to 1.0 scale)
    hook_strength: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Strength of the opening hook (0=weak, 1=very strong)"
    )
    standalone_clarity: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="How well the clip works standalone without context"
    )
    narrative_completeness: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Whether the clip has a complete narrative arc"
    )
    emotional_intensity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Emotional intensity of the clip content"
    )
    topic_relevance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Relevance to main topic of the source content"
    )

    model_config = {"extra": "forbid"}


class LLMDiscoveryResponse(BaseModel):
    """Structured response from LLM for clip discovery."""

    clips: list[LLMClipSuggestion] = Field(..., max_length=10)

    model_config = {"extra": "forbid"}
