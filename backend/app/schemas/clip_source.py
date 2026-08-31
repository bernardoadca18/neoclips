"""ClipSource schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ClipSourceBase(BaseModel):
    """Base schema for ClipSource."""

    mode: str
    source_policy_id: UUID | None = None
    original_reference: str | None = Field(None, max_length=1024)
    creator: str | None = Field(None, max_length=255)
    program: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=500)
    media_project_id: UUID | None = None
    media_session_id: UUID | None = None
    media_session_label: str | None = None
    media_id: UUID | None = None
    media_initial_job_id: UUID | None = None
    transcription_id: UUID | None = None
    transcription_job_id: UUID | None = None
    source_sha256: str | None = Field(None, min_length=64, max_length=64)
    phase_started_at: datetime | None = None
    operator_acknowledged: bool = False

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = {"safe_automated", "manual_override"}
        if v not in valid:
            raise ValueError(f"mode must be one of {valid}")
        return v

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> "ClipSourceBase":
        if self.mode == "safe_automated" and self.source_policy_id is None:
            raise ValueError("safe_automated mode requires source_policy_id")
        if self.mode == "manual_override" and not self.operator_acknowledged:
            raise ValueError("manual_override mode requires operator_acknowledged=true")
        return self


class ClipSourceCreate(ClipSourceBase):
    """Schema for creating a ClipSource."""

    model_config = {"extra": "forbid"}


class ClipSourceUpdate(BaseModel):
    """Schema for updating a ClipSource.

    System-managed fields (media_project_id, media_session_id, media_id,
    transcription_id, source_sha256) are not allowed to be set via API.
    """

    source_policy_id: UUID | None = None
    original_reference: str | None = Field(None, max_length=1024)
    creator: str | None = Field(None, max_length=255)
    program: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=500)
    status: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"pending", "ingesting", "transcribing", "ready_for_discovery", "ready", "failed", "blocked"}
        if v not in valid:
            raise ValueError(f"status must be one of {valid}")
        return v


class ClipSourceResponse(ClipSourceBase):
    """Schema for ClipSource responses."""

    id: UUID
    rights_status: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
