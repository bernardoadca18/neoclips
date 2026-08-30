"""Unit tests for ClipWorkflow service state transitions."""

import pytest

from app.services.clip_workflow_service import ClipWorkflowService, VALID_TRANSITIONS


def test_valid_transitions_from_created():
    """Created can transition to ingesting or cancelled."""
    assert "ingesting" in VALID_TRANSITIONS["created"]
    assert "cancelled" in VALID_TRANSITIONS["created"]
    assert "discovering" not in VALID_TRANSITIONS["created"]


def test_valid_transitions_from_failed():
    """Failed can only transition to created (retry)."""
    assert "created" in VALID_TRANSITIONS["failed"]
    assert "cancelled" not in VALID_TRANSITIONS["failed"]


def test_terminal_states_have_no_transitions():
    """Terminal states have no valid transitions."""
    assert len(VALID_TRANSITIONS["ready_for_review"]) == 0
    assert len(VALID_TRANSITIONS["cancelled"]) == 0
    assert len(VALID_TRANSITIONS["blocked"]) == 0


def test_awaiting_selection_can_only_transition_to_rendering_or_cancelled():
    """awaiting_selection has limited valid transitions."""
    valid = VALID_TRANSITIONS["awaiting_selection"]
    assert "rendering" in valid
    assert "cancelled" in valid
    assert len(valid) == 2
