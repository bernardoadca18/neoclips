"""SourcePolicy schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SourcePolicyBase(BaseModel):
    """Base schema for SourcePolicy."""

    name: str = Field(..., min_length=1, max_length=255)
    version: str = Field(..., min_length=1, max_length=50)
    verification_status: str = Field(default="unverified")
    commercial_use_allowed: bool = False
    derivatives_allowed: bool = False
    monetization_allowed: bool = False
    allowed_platforms: list[str] | None = None
    max_clip_duration_seconds: int | None = Field(None, gt=0)
    attribution_required: bool = False
    attribution_template: str | None = None
    embargo_seconds: int = Field(0, ge=0)
    evidence_uri: str | None = Field(None, max_length=1024)
    evidence_note: str | None = None

    @field_validator("verification_status")
    @classmethod
    def validate_verification_status(cls, v: str) -> str:
        valid = {"verified", "unverified", "blocked"}
        if v not in valid:
            raise ValueError(f"verification_status must be one of {valid}")
        return v


class SourcePolicyCreate(SourcePolicyBase):
    """Schema for creating a SourcePolicy."""

    model_config = {"extra": "forbid"}


class SourcePolicyUpdate(BaseModel):
    """Schema for updating a SourcePolicy.

    Name and version are immutable after creation.
    verified_at is managed internally by the service when verification_status changes.
    """

    verification_status: str | None = None
    commercial_use_allowed: bool | None = None
    derivatives_allowed: bool | None = None
    monetization_allowed: bool | None = None
    allowed_platforms: list[str] | None = None
    max_clip_duration_seconds: int | None = Field(None, gt=0)
    attribution_required: bool | None = None
    attribution_template: str | None = None
    embargo_seconds: int | None = Field(None, ge=0)
    evidence_uri: str | None = Field(None, max_length=1024)
    evidence_note: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("verification_status")
    @classmethod
    def validate_verification_status(cls, v: str | None) -> str | None:
        if v is None:
            return v
        valid = {"verified", "unverified", "blocked"}
        if v not in valid:
            raise ValueError(f"verification_status must be one of {valid}")
        return v


class SourcePolicyResponse(SourcePolicyBase):
    """Schema for SourcePolicy responses."""

    id: UUID
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
