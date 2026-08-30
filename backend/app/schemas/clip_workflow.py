"""ClipWorkflow schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ClipWorkflowBase(BaseModel):
    """Base schema for ClipWorkflow."""

    source_id: UUID


class ClipWorkflowCreate(ClipWorkflowBase):
    """Schema for creating a ClipWorkflow."""

    model_config = {"extra": "forbid"}


class ClipWorkflowUpdate(BaseModel):
    """Schema for updating a ClipWorkflow."""

    status: str | None = None
    current_phase: str | None = None
    attempt_count: int | None = Field(None, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_error_category: str | None = None
    last_error_message: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {
            "created", "ingesting", "transcribing", "discovering", "observing",
            "reranking", "awaiting_selection", "rendering", "packaging", "qa",
            "ready_for_review", "blocked", "failed", "cancelled"
        }
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v


class ClipWorkflowResponse(ClipWorkflowBase):
    """Schema for ClipWorkflow responses."""

    id: UUID
    status: str
    current_phase: str | None
    attempt_count: int
    started_at: datetime | None
    completed_at: datetime | None
    last_error_category: str | None
    last_error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
