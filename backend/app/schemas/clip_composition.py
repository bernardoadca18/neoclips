"""Pydantic schemas for Clip Composition API (Stage 5)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClipCompositionCreate(BaseModel):
    """Request body for creating a clip composition."""

    composition_params: dict | None = Field(
        default=None,
        description="Strategy-specific parameters. For ADD_CONTEXT: {context_before_seconds, context_after_seconds}. For TRIM: {trim_point_seconds}.",
    )

    model_config = ConfigDict(extra="forbid")


class ClipCompositionRead(BaseModel):
    """Response body for clip composition."""

    id: UUID
    workflow_id: UUID
    source_id: UUID | None
    plan_id: UUID
    source_start_seconds: float
    source_end_seconds: float
    duration_seconds: float
    source_start_segment_id: UUID | None
    source_end_segment_id: UUID | None
    strategy: str
    render_profile: str
    composition_params: dict | None
    status: str
    render_job_id: UUID | None
    output_media_id: UUID | None
    fingerprint: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClipCompositionUpdate(BaseModel):
    """Request body for updating a clip composition."""

    status: str | None = Field(default=None, description="New status")
    render_job_id: UUID | None = Field(default=None, description="Render job ID")
    output_media_id: UUID | None = Field(default=None, description="Output media ID")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"pending", "validating", "ready", "rendering", "completed", "failed"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v

    model_config = ConfigDict(extra="forbid")
