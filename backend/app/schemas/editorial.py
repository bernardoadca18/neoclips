"""Pydantic schemas for Editorial Suitability Analysis and Short Editorial Plan."""

import typing
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# --- EditorialSuitabilityAnalysis Schemas ---


class EditorialSuitabilityAnalysisBase(BaseModel):
    """Base schema for EditorialSuitabilityAnalysis."""

    context_before_seconds: float = Field(default=45.0, ge=0, description="Seconds of context before candidate")
    context_after_seconds: float = Field(default=40.0, ge=0, description="Seconds of context after candidate")


class EditorialSuitabilityAnalysisCreate(EditorialSuitabilityAnalysisBase):
    """Schema for creating an EditorialSuitabilityAnalysis."""

    candidate_id: UUID = Field(..., description="Clip candidate ID to analyze")


class EditorialSuitabilityAnalysisUpdate(BaseModel):
    """Schema for updating an EditorialSuitabilityAnalysis."""

    status: str | None = None
    standalone_score: int | None = None
    context_dependency: str | None = None
    hook_strength: int | None = None
    payoff_strength: int | None = None
    ending_completeness: int | None = None
    reference_dependency_level: str | None = None
    reference_dependency_examples: dict[str, typing.Any] | None = None
    recommended_strategy: str | None = None
    recommended_start_segment_id: UUID | None = None
    recommended_end_segment_id: UUID | None = None
    analysis_summary: str | None = None
    raw_llm_response: str | None = None
    error_message: str | None = None
    completed_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"pending", "processing", "completed", "failed"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v

    @field_validator("standalone_score", "hook_strength", "payoff_strength", "ending_completeness")
    @classmethod
    def validate_score_0_100(cls, v: int | None) -> int | None:
        if v is None:
            return v
        if not (0 <= v <= 100):
            raise ValueError("score must be between 0 and 100")
        return v

    @field_validator("context_dependency", "reference_dependency_level")
    @classmethod
    def validate_dependency_level(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"none", "low", "medium", "high", "critical"}
        if v not in valid:
            raise ValueError(f"dependency level must be one of {valid}")
        return v

    @field_validator("recommended_strategy")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT", "REAUTHOR", "REJECT"}
        if v not in valid:
            raise ValueError(f"strategy must be one of {valid}")
        return v


class EditorialSuitabilityAnalysisRead(BaseModel):
    """Schema for reading an EditorialSuitabilityAnalysis."""

    id: UUID
    candidate_id: UUID
    source_id: UUID | None
    transcription_id: UUID | None
    strategy_id: str | None
    strategy_version: str | None
    prompt_id: str | None
    prompt_version: str | None
    prompt_hash: str | None
    config_snapshot: str | None
    request_fingerprint: str | None
    requested_combo: str | None
    resolved_model: str | None
    context_before_seconds: float
    context_after_seconds: float
    status: str
    error_message: str | None
    standalone_score: int | None
    context_dependency: str | None
    hook_strength: int | None
    payoff_strength: int | None
    ending_completeness: int | None
    reference_dependency_level: str | None
    reference_dependency_examples: dict[str, typing.Any] | None
    recommended_strategy: str | None
    recommended_start_segment_id: UUID | None
    recommended_end_segment_id: UUID | None
    analysis_summary: str | None
    raw_llm_response: str | None
    started_at: datetime | None
    completed_at: datetime | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- ShortEditorialPlan Schemas ---


class ShortEditorialPlanBase(BaseModel):
    """Base schema for ShortEditorialPlan."""

    strategy: str = Field(..., description="Editorial strategy")
    decision_source: str = Field(
        default="model_recommendation",
        description="Source of the decision"
    )


class ShortEditorialPlanCreate(ShortEditorialPlanBase):
    """Schema for creating a ShortEditorialPlan."""

    candidate_id: UUID = Field(..., description="Clip candidate ID")
    analysis_id: UUID | None = Field(default=None, description="Optional analysis ID")
    source_start_segment_id: UUID | None = None
    source_end_segment_id: UUID | None = None
    source_start_seconds: float = Field(..., ge=0)
    source_end_seconds: float = Field(..., gt=0)
    duration_seconds: float = Field(..., gt=0)

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        valid = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT", "REAUTHOR", "REJECT"}
        if v not in valid:
            raise ValueError(f"strategy must be one of {valid}")
        return v

    @field_validator("decision_source")
    @classmethod
    def validate_decision_source(cls, v: str) -> str:
        valid = {"model_recommendation", "human_override"}
        if v not in valid:
            raise ValueError(f"decision_source must be one of {valid}")
        return v


class ShortEditorialPlanUpdate(BaseModel):
    """Schema for updating a ShortEditorialPlan."""

    strategy: str | None = None
    decision_source: str | None = None
    source_start_segment_id: UUID | None = None
    source_end_segment_id: UUID | None = None
    source_start_seconds: float | None = None
    source_end_seconds: float | None = None
    duration_seconds: float | None = None
    rejection_reason: str | None = None
    status: str | None = None

    @field_validator("strategy")
    @classmethod
    def validate_strategy(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT", "REAUTHOR", "REJECT"}
        if v not in valid:
            raise ValueError(f"strategy must be one of {valid}")
        return v

    @field_validator("decision_source")
    @classmethod
    def validate_decision_source(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"model_recommendation", "human_override"}
        if v not in valid:
            raise ValueError(f"decision_source must be one of {valid}")
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"draft", "ready", "rejected", "invalidated"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v


class ShortEditorialPlanRead(BaseModel):
    """Schema for reading a ShortEditorialPlan."""

    id: UUID
    workflow_id: UUID
    source_id: UUID | None
    candidate_id: UUID
    analysis_id: UUID | None
    strategy: str
    decision_source: str
    source_start_segment_id: UUID | None
    source_end_segment_id: UUID | None
    source_start_seconds: float
    source_end_seconds: float
    duration_seconds: float
    recommended_strategy: str | None
    recommended_start_segment_id: UUID | None
    recommended_end_segment_id: UUID | None
    rejection_reason: str | None
    status: str
    plan_version: str | None
    config_snapshot: str | None
    fingerprint: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# --- LLM Response Schemas for Editorial Analysis ---


class LLMEditorialAnalysisResponse(BaseModel):
    """Structured response from LLM for editorial suitability analysis."""

    standalone_score: int = Field(..., ge=0, le=100)
    context_dependency: str = Field(..., description="none, low, medium, high, critical")
    hook_strength: int = Field(..., ge=0, le=100)
    payoff_strength: int = Field(..., ge=0, le=100)
    ending_completeness: int = Field(..., ge=0, le=100)
    reference_dependency_level: str = Field(..., description="none, low, medium, high, critical")
    reference_dependency_examples: list[str] = Field(default_factory=list)
    recommended_strategy: str = Field(..., description="USE_DIRECTLY, TRIM, ADD_CONTEXT, REAUTHOR, REJECT")
    recommended_start_segment_id: UUID | None = None
    recommended_end_segment_id: UUID | None = None
    analysis_summary: str = Field(..., min_length=1)

    @field_validator("context_dependency", "reference_dependency_level")
    @classmethod
    def validate_dependency(cls, v: str) -> str:
        valid = {"none", "low", "medium", "high", "critical"}
        if v not in valid:
            raise ValueError(f"must be one of {valid}")
        return v

    @field_validator("recommended_strategy")
    @classmethod
    def validate_strategy(cls, v: str) -> str:
        valid = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT", "REAUTHOR", "REJECT"}
        if v not in valid:
            raise ValueError(f"must be one of {valid}")
        return v

    model_config = {"extra": "forbid"}


# --- Candidate Shortlist Schemas ---


class CandidateShortlistItem(BaseModel):
    """A single candidate in the shortlist view."""

    id: UUID
    run_id: UUID
    canonical_start_seconds: float
    canonical_end_seconds: float
    duration_seconds: float
    title: str | None
    summary: str | None
    hook_type: str | None
    score_v1: float | None
    discovery_rank: int | None
    is_duplicate: bool
    selected: bool
    selection_rank: int | None
    candidate_fingerprint: str | None
    has_analysis: bool = Field(..., description="Whether analysis exists for this candidate")
    has_plan: bool = Field(..., description="Whether editorial plan exists for this candidate")

    model_config = {"from_attributes": True}


class CandidateShortlistResponse(BaseModel):
    """Response for candidate shortlist endpoint."""

    run_id: UUID
    workflow_id: UUID
    total_candidates: int
    returned_count: int
    candidates: list[CandidateShortlistItem]


# --- Candidate Selection Schemas ---


class CandidateSelectionRequest(BaseModel):
    """Request for selecting/unselecting a candidate."""

    selected: bool = Field(..., description="True to select, False to unselect")
    selection_rank: int | None = Field(default=None, ge=1, description="Optional rank for ordering")


class CandidateSelectionResponse(BaseModel):
    """Response for candidate selection endpoint."""

    candidate_id: UUID
    selected: bool
    selection_rank: int | None
    message: str
