"""Unit tests for ClipWorkflow schema validation."""

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.schemas.clip_workflow import ClipWorkflowCreate, ClipWorkflowUpdate


def test_clip_workflow_create_valid():
    """Valid workflow creation schema."""
    from uuid import uuid4
    workflow = ClipWorkflowCreate(source_id=uuid4())
    assert workflow.source_id is not None


def test_clip_workflow_update_valid_status():
    """Valid status values are accepted."""
    update = ClipWorkflowUpdate(status="discovering")
    assert update.status == "discovering"


def test_clip_workflow_update_invalid_status():
    """Invalid status raises validation error."""
    with pytest.raises(ValueError, match="status must be one of"):
        ClipWorkflowUpdate(status="invalid_status")


def test_clip_workflow_update_attempt_count_validation():
    """attempt_count must be >= 0."""
    update = ClipWorkflowUpdate(attempt_count=5)
    assert update.attempt_count == 5

    with pytest.raises(ValueError):
        ClipWorkflowUpdate(attempt_count=-1)
