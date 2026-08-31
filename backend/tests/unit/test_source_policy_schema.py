"""Unit tests for SourcePolicy schema validation."""

import pytest
from pydantic import ValidationError as PydanticValidationError  # noqa: F401

from app.schemas.source_policy import SourcePolicyCreate


def test_source_policy_create_valid():
    """Valid policy creation schema."""
    policy = SourcePolicyCreate(
        name="Test Policy",
        version="1.0",
        verification_status="unverified",
    )
    assert policy.name == "Test Policy"
    assert policy.version == "1.0"


def test_source_policy_create_invalid_verification_status():
    """Invalid verification_status raises validation error."""
    with pytest.raises(ValueError, match="verification_status must be one of"):
        SourcePolicyCreate(
            name="Test Policy",
            version="1.0",
            verification_status="invalid_status",
        )


def test_source_policy_create_max_clip_duration_positive():
    """max_clip_duration_seconds must be > 0."""
    with pytest.raises(ValueError):
        SourcePolicyCreate(
            name="Test Policy",
            version="1.0",
            max_clip_duration_seconds=0,
        )


def test_source_policy_create_embargo_non_negative():
    """embargo_seconds must be >= 0."""
    with pytest.raises(ValueError):
        SourcePolicyCreate(
            name="Test Policy",
            version="1.0",
            embargo_seconds=-1,
        )
