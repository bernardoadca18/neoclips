"""Unit tests for ClipSource schema validation."""

from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.clip_source import ClipSourceCreate, ClipSourceUpdate


def test_clip_source_create_safe_automated_requires_policy():
    """safe_automated mode requires source_policy_id."""
    with pytest.raises(ValueError, match="source_policy_id"):
        ClipSourceCreate(mode="safe_automated")


def test_clip_source_create_manual_override_requires_acknowledgment():
    """manual_override mode requires operator_acknowledged=true."""
    with pytest.raises(ValueError, match="operator_acknowledged"):
        ClipSourceCreate(mode="manual_override", operator_acknowledged=False)


def test_clip_source_create_manual_override_valid():
    """manual_override mode with acknowledgment is valid."""
    source = ClipSourceCreate(
        mode="manual_override",
        operator_acknowledged=True,
        title="Test Source",
    )
    assert source.mode == "manual_override"
    assert source.operator_acknowledged is True


def test_clip_source_create_invalid_mode():
    """Invalid mode raises validation error."""
    with pytest.raises(ValueError, match="mode must be one of"):
        ClipSourceCreate(mode="invalid_mode")


def test_clip_source_update_valid_status():
    """Valid status values are accepted."""
    update = ClipSourceUpdate(status="ready")
    assert update.status == "ready"


def test_clip_source_update_invalid_status():
    """Invalid status raises validation error."""
    with pytest.raises(ValueError, match="status must be one of"):
        ClipSourceUpdate(status="invalid_status")


def test_clip_source_create_with_policy():
    """Creating source with policy reference."""
    policy_id = uuid4()
    source = ClipSourceCreate(
        mode="safe_automated",
        source_policy_id=policy_id,
        title="Test Source",
    )
    assert source.source_policy_id == policy_id
