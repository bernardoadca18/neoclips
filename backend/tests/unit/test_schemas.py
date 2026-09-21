"""Unit tests for ClipSource schema validation."""

from uuid import uuid4

import pytest

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


def test_clip_source_update_status_not_allowed():
    """Status field is not allowed in public update schema."""
    with pytest.raises(Exception, match="Extra inputs are not permitted"):
        ClipSourceUpdate(status="ready")


def test_clip_source_update_internal_fields_not_allowed():
    """Internal fields are not allowed in public update schema."""
    from uuid import uuid4
    with pytest.raises(Exception, match="Extra inputs are not permitted"):
        ClipSourceUpdate(media_project_id=uuid4())


def test_clip_source_create_internal_fields_not_allowed():
    """Internal fields are not allowed in public create schema."""
    from uuid import uuid4
    policy_id = uuid4()
    with pytest.raises(Exception, match="Extra inputs are not permitted"):
        ClipSourceCreate(
            mode="safe_automated",
            source_policy_id=policy_id,
            media_project_id=uuid4(),  # Internal field, should be rejected
        )


def test_clip_source_create_with_policy():
    """Creating source with policy reference."""
    policy_id = uuid4()
    source = ClipSourceCreate(
        mode="safe_automated",
        source_policy_id=policy_id,
        title="Test Source",
    )
    assert source.source_policy_id == policy_id
