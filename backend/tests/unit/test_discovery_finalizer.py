"""Direct unit tests for finalize_discovery task.

Tests focus on critical behaviors:
- Early finalizer returns not_ready (does NOT mutate run state)
- Idempotency: already finalized runs stay finalized
- All windows failed -> run.failed
- Partial failure -> run.completed_with_errors
"""

import json
from hashlib import sha256
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.entities import ClipWorkflow, DiscoveryRun
from app.prompts.clip_discovery_prompts import get_clip_discovery_prompt


def make_valid_config_snapshot() -> str:
    """Create a valid config_snapshot JSON string."""
    prompt_text = get_clip_discovery_prompt("clip_discovery_v1", "1.0.0")
    prompt_hash = sha256(prompt_text.encode()).hexdigest()

    return json.dumps({
        "strategy": {"id": "transcript_v1", "version": "1.0.0"},
        "prompt": {
            "id": "clip_discovery_v1",
            "version": "1.0.0",
            "hash": prompt_hash,
        },
        "llm": {
            "provider": "9router",
            "model": "neoclips-discovery",
            "temperature": 0.3,
            "max_candidates_per_window": 10,
        },
        "window": {"duration_seconds": 300, "overlap_seconds": 60},
        "scoring": {"version": "clip_score_v1"},
        "dedup": {"version": "temporal_iou_v1", "iou_threshold": 0.5},
    })


class TestFinalizerIdempotency:
    """Tests for finalizer idempotency - most critical."""

    @pytest.mark.asyncio
    async def test_already_completed_stays_completed(self):
        """Already completed run stays completed."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="completed",
            total_windows=2,
            processed_windows=2,
            completed_windows=2,
            failed_windows=0,
            config_snapshot=make_valid_config_snapshot(),
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        mock_session.execute.return_value = run_result

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _finalize_discovery(run_id)

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_already_failed_stays_failed(self):
        """Already failed run stays failed."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="failed",
            total_windows=2,
            processed_windows=2,
            completed_windows=0,
            failed_windows=2,
            error_message="Previous error",
            config_snapshot=make_valid_config_snapshot(),
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run
        mock_session.execute.return_value = run_result

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _finalize_discovery(run_id)

        assert result["status"] == "failed"
        assert run.error_message == "Previous error"


class TestFinalizationOutcomes:
    """Tests for finalization outcome states."""

    @pytest.mark.asyncio
    async def test_all_windows_failed_run_status(self):
        """All windows failed -> run.status = failed."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="running",
            total_windows=2,
            processed_windows=2,
            completed_windows=0,
            failed_windows=2,
            config_snapshot=make_valid_config_snapshot(),
        )

        workflow = ClipWorkflow(
            id=workflow_id,
            source_id=uuid4(),
            status="discovering",
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = []

        window_result = MagicMock()
        window_result.fetchall.return_value = [("failed",), ("failed",)]

        mock_session.execute.side_effect = [
            run_result,
            workflow_result,
            candidate_result,
            window_result,
        ]

        mock_workflow_service = MagicMock()
        mock_workflow_service.transition_status = AsyncMock()

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.tasks.discovery_tasks.ClipWorkflowService") as mock_service_class:
                mock_service_class.return_value = mock_workflow_service

                await _finalize_discovery(run_id)

        assert run.status == "failed"
        assert "All windows failed" in run.error_message

    @pytest.mark.asyncio
    async def test_partial_failure_run_status(self):
        """Partial failure -> run.status = completed_with_errors."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="running",
            total_windows=3,
            processed_windows=3,
            completed_windows=2,
            failed_windows=1,
            config_snapshot=make_valid_config_snapshot(),
        )

        workflow = ClipWorkflow(
            id=workflow_id,
            source_id=uuid4(),
            status="discovering",
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = []

        window_result = MagicMock()
        window_result.fetchall.return_value = [
            ("completed",), ("completed",), ("failed",)
        ]

        mock_session.execute.side_effect = [
            run_result,
            workflow_result,
            candidate_result,
            window_result,
        ]

        mock_workflow_service = MagicMock()
        mock_workflow_service.transition_status = AsyncMock()

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.tasks.discovery_tasks.ClipWorkflowService") as mock_service_class:
                mock_service_class.return_value = mock_workflow_service

                await _finalize_discovery(run_id)

        assert run.status == "completed_with_errors"
        assert "1 windows failed" in run.error_message


class TestEarlyFinalizerReturns:
    """Tests for early finalizer return values without mutation."""

    @pytest.mark.asyncio
    async def test_early_finalizer_returns_not_ready_without_mutation(self):
        """Early finalizer returns not_ready without mutating run state."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        # Run that looks "running" but has incomplete windows
        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="running",
            total_windows=3,
            processed_windows=2,
            completed_windows=1,
            failed_windows=1,
            config_snapshot=make_valid_config_snapshot(),
        )

        workflow = ClipWorkflow(
            id=workflow_id,
            source_id=uuid4(),
            status="discovering",
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = []

        # Windows: 1 completed, 1 failed, 1 pending (not all processed)
        window_result = MagicMock()
        window_result.fetchall.return_value = [
            ("completed",), ("failed",), ("pending",)
        ]

        mock_session.execute.side_effect = [
            run_result,
            workflow_result,
            candidate_result,
            window_result,
        ]

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _finalize_discovery(run_id)

        # Key assertions:
        # 1. Returns not_ready status
        assert result["status"] == "not_ready"
        # 2. Returns accurate counts
        assert result["pending"] == 1
        assert result["failed"] == 1
        assert result["completed"] == 1
        # 3. Run stays "running" - NOT mutated
        assert run.status == "running"


class TestFinalizerEdgeCases:
    """Tests for finalizer edge cases."""

    @pytest.mark.asyncio
    async def test_run_not_found_returns_error(self):
        """Run not found returns error status."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = None  # Run not found
        mock_session.execute.return_value = run_result

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await _finalize_discovery(run_id)

        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_all_windows_completed_successfully(self):
        """All windows completed -> run.status = completed."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="running",
            total_windows=2,
            processed_windows=2,
            completed_windows=2,
            failed_windows=0,
            total_candidates=5,
            config_snapshot=make_valid_config_snapshot(),
        )

        workflow = ClipWorkflow(
            id=workflow_id,
            source_id=uuid4(),
            status="discovering",
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = []

        window_result = MagicMock()
        window_result.fetchall.return_value = [("completed",), ("completed",)]

        mock_session.execute.side_effect = [
            run_result,
            workflow_result,
            candidate_result,
            window_result,
        ]

        mock_workflow_service = MagicMock()
        mock_workflow_service.transition_status = AsyncMock()

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.tasks.discovery_tasks.ClipWorkflowService") as mock_service_class:
                mock_service_class.return_value = mock_workflow_service

                result = await _finalize_discovery(run_id)

        assert run.status == "completed"
        assert result["status"] == "completed"
        assert run.error_message is None

    @pytest.mark.asyncio
    async def test_workflow_transitioned_to_awaiting_selection(self):
        """Workflow is transitioned to awaiting_selection on completion."""
        from app.tasks.discovery_tasks import _finalize_discovery

        run_id = uuid4()
        workflow_id = uuid4()

        run = DiscoveryRun(
            id=run_id,
            workflow_id=workflow_id,
            status="running",
            total_windows=1,
            processed_windows=1,
            completed_windows=1,
            failed_windows=0,
            total_candidates=3,
            config_snapshot=make_valid_config_snapshot(),
        )

        workflow = ClipWorkflow(
            id=workflow_id,
            source_id=uuid4(),
            status="discovering",
        )

        mock_session = AsyncMock()
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        candidate_result = MagicMock()
        candidate_result.scalars.return_value.all.return_value = []

        window_result = MagicMock()
        window_result.fetchall.return_value = [("completed",)]

        mock_session.execute.side_effect = [
            run_result,
            workflow_result,
            candidate_result,
            window_result,
        ]

        mock_workflow_service = MagicMock()
        mock_workflow_service.transition_status = AsyncMock()

        with patch("app.tasks.discovery_tasks.async_session_factory") as mock_factory:
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            with patch("app.tasks.discovery_tasks.ClipWorkflowService") as mock_service_class:
                mock_service_class.return_value = mock_workflow_service

                await _finalize_discovery(run_id)

        # Workflow service transition_status should be called
        mock_workflow_service.transition_status.assert_called_once_with(
            workflow_id, "awaiting_selection"
        )
