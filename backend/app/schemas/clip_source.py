"""ClipSource schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class ClipSourceOperatorInput(BaseModel):
    """Operator-provided fields for ClipSource creation.

    These are the only fields that can be set by operators via the public API.
    Internal/authoritative fields (media_project_id, media_session_id, etc.)
    are populated by the system via Media Indexer adoption.
    """

    mode: str
    source_policy_id: UUID | None = None
    operator_acknowledged: bool = False
    original_reference: str | None = Field(None, max_length=1024)
    creator: str | None = Field(None, max_length=255)
    program: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=500)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = {"safe_automated", "manual_override"}
        if v not in valid:
            raise ValueError(f"mode must be one of {valid}")
        return v

    @model_validator(mode="after")
    def validate_mode_requirements(self) -> "ClipSourceOperatorInput":
        if self.mode == "safe_automated" and self.source_policy_id is None:
            raise ValueError("safe_automated mode requires source_policy_id")
        if self.mode == "manual_override" and not self.operator_acknowledged:
            raise ValueError("manual_override mode requires operator_acknowledged=true")
        return self

    model_config = {"extra": "forbid"}


class ClipSourceCreate(ClipSourceOperatorInput):
    """Schema for creating a ClipSource via public API.

    Inherits operator-input fields only. Internal fields are set by the system.
    """

    pass


class ClipSourceInternalData(BaseModel):
    """Internal/authoritative fields populated by Media Indexer.

    These fields are NEVER accepted via public API.
    They are populated by the system during MediaSession adoption.
    """

    media_project_id: UUID | None = None
    media_session_id: UUID | None = None
    media_session_label: str | None = None
    media_id: UUID | None = None
    media_initial_job_id: UUID | None = None
    transcription_id: UUID | None = None
    transcription_job_id: UUID | None = None
    source_sha256: str | None = Field(None, min_length=64, max_length=64)
    phase_started_at: datetime | None = None


class ClipSourceUpdate(BaseModel):
    """Schema for updating a ClipSource via public API.

    Only operator-controlled fields can be updated.
    System-managed fields (media_project_id, media_session_id, media_id,
    transcription_id, source_sha256, status, rights_status) are not allowed.
    Status transitions are handled internally by the service layer.
    """

    source_policy_id: UUID | None = None
    original_reference: str | None = Field(None, max_length=1024)
    creator: str | None = Field(None, max_length=255)
    program: str | None = Field(None, max_length=255)
    title: str | None = Field(None, max_length=500)

    model_config = {"extra": "forbid"}


class ClipSourceResponse(BaseModel):
    """Schema for ClipSource responses.

    Includes all fields: operator input, internal data, and system-managed status.
    """

    id: UUID
    mode: str
    source_policy_id: UUID | None = None
    original_reference: str | None = None
    creator: str | None = None
    program: str | None = None
    title: str | None = None
    operator_acknowledged: bool = False

    # Internal fields (populated by Media Indexer)
    media_project_id: UUID | None = None
    media_session_id: UUID | None = None
    media_session_label: str | None = None
    media_id: UUID | None = None
    media_initial_job_id: UUID | None = None
    transcription_id: UUID | None = None
    transcription_job_id: UUID | None = None
    source_sha256: str | None = None
    phase_started_at: datetime | None = None

    # System-managed status fields
    rights_status: str
    status: str

    # Timestamps
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
