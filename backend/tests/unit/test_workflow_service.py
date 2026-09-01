"""Unit tests for ClipWorkflow service state transitions."""

import pytest  # noqa: F401

from app.services.clip_workflow_service import VALID_TRANSITIONS


def test_valid_transitions_from_created():
    """Created can transition to discovering or cancelled.

    Note: ClipWorkflow no longer has ingesting/transcribing states.
    ClipSource owns Media Indexer pipeline states.
    ClipWorkflow starts discovering when ClipSource is ready_for_discovery.
    """
    assert "discovering" in VALID_TRANSITIONS["created"]
    assert "cancelled" in VALID_TRANSITIONS["created"]
    assert "ingesting" not in VALID_TRANSITIONS["created"]


def test_valid_transitions_from_failed():
    """Failed can only transition to created (retry)."""
    assert "created" in VALID_TRANSITIONS["failed"]
    assert "cancelled" not in VALID_TRANSITIONS["failed"]


def test_terminal_states_have_no_transitions():
    """Terminal states have no valid transitions."""
    assert len(VALID_TRANSITIONS["ready_for_review"]) == 0
    assert len(VALID_TRANSITIONS["cancelled"]) == 0
    assert len(VALID_TRANSITIONS["blocked"]) == 0


def test_awaiting_selection_can_only_transition_to_planning_or_cancelled():
    """awaiting_selection has limited valid transitions.

    Stage 4 adds 'planning' state for editorial analysis and plan creation.
    awaiting_selection transitions to planning, then planning transitions to rendering.
    """
    valid = VALID_TRANSITIONS["awaiting_selection"]
    assert "planning" in valid
    assert "cancelled" in valid
    assert len(valid) == 2


def test_planning_can_transition_to_rendering_failed_or_cancelled():
    """planning state supports transitions to rendering, failed, or cancelled."""
    valid = VALID_TRANSITIONS["planning"]
    assert "rendering" in valid
    assert "failed" in valid
    assert "cancelled" in valid
    assert len(valid) == 3
