"""Unit tests for discovery task behaviors.

Tests cover:
- process_window: success, failure, stale recovery, next-window scheduling
- finalize_discovery: completion, partial failure, deduplication

Uses mocked async_session_factory context manager to avoid database dependencies.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.models.entities import ClipCandidate, ClipSource, ClipWorkflow, DiscoveryRun, DiscoveryWindow
from app.tasks.discovery_tasks import (
    STALE_WINDOW_TIMEOUT_SECONDS,
    _schedule_next_or_finalizer,
    compute_candidate_fingerprint,
)


@pytest.fixture
def mock_session():
    """Create a mock async session with all necessary methods."""
    session = AsyncMock()
    session.begin_nested = MagicMock(return_value=AsyncMock())
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    """Mock async_session_factory to return mock session."""
    # Create an async context manager
    async_context = AsyncMock()
    async_context.__aenter__ = AsyncMock(return_value=mock_session)
    async_context.__aexit__ = AsyncMock(return_value=None)

    with patch("app.tasks.discovery_tasks.async_session_factory", return_value=async_context):
        yield mock_session


@pytest.fixture
def mock_settings():
    """Mock settings."""
    with patch("app.tasks.discovery_tasks.settings") as mock:
        mock.media_indexer_base_url = "http://test"
        mock.media_indexer_timeout_seconds = 30
        mock.litellm_model = "test-model"
        yield mock


class TestComputeCandidateFingerprint:
    """Tests for fingerprint computation."""

    def test_fingerprint_is_consistent(self):
        """Same timestamps produce same fingerprint."""
        fp1 = compute_candidate_fingerprint(10.0, 60.0)
        fp2 = compute_candidate_fingerprint(10.0, 60.0)
        assert fp1 == fp2

    def test_fingerprint_is_sha256_hex(self):
        """Fingerprint is 64-character hex string."""
        fp = compute_candidate_fingerprint(10.0, 60.0)
        assert len(fp) == 64
        assert all(c in "0123456789abcdef" for c in fp)

    def test_different_timestamps_different_fingerprint(self):
        """Different timestamps produce different fingerprints."""
        fp1 = compute_candidate_fingerprint(10.0, 60.0)
        fp2 = compute_candidate_fingerprint(10.0, 61.0)
        assert fp1 != fp2


class TestProcessWindowSuccess:
    """Tests for successful window processing."""

    @pytest.mark.asyncio
    async def test_window_not_found_returns_error(self, mock_session_factory):
        """Window not found returns error dict."""
        # Mock window query returns None
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session_factory.execute = AsyncMock(return_value=mock_result)

        from app.tasks.discovery_tasks import _process_window

        result = await _process_window(uuid4(), uuid4())

        assert result["status"] == "not_found"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_run_not_found_returns_error(self, mock_session_factory):
        """Run not found returns error dict."""
        window = DiscoveryWindow(
            id=uuid4(),
            run_id=uuid4(),
            window_index=0,
            start_seconds=0,
            end_seconds=300,
            status="pending",
        )

        # First call returns window, second returns None
        results = [
            MagicMock(scalar_one_or_none=MagicMock(return_value=window)),
            MagicMock(scalar_one_or_none=MagicMock(return_value=None)),
        ]
        mock_session_factory.execute = AsyncMock(side_effect=results)

        from app.tasks.discovery_tasks import _process_window

        result = await _process_window(window.id, window.run_id)

        assert result["status"] == "not_found"
        assert "Run" in result["error"]


class TestProcessWindowStaleRecovery:
    """Tests for stale window recovery."""

    @pytest.mark.asyncio
    async def test_stale_window_is_recovered(self, mock_session_factory, mock_settings):
        """Window stuck in processing for > 10min is recovered."""
        run_id = uuid4()
        window_id = uuid4()

        # Create window stuck in processing for 15 minutes
        stale_time = datetime.now(UTC) - timedelta(seconds=STALE_WINDOW_TIMEOUT_SECONDS + 300)
        window = DiscoveryWindow(
            id=window_id,
            run_id=run_id,
            window_index=0,
            start_seconds=0,
            end_seconds=300,
            status="processing",
            processing_started_at=stale_time,
            attempt_count=0,
        )

        run = DiscoveryRun(
            id=run_id,
            workflow_id=uuid4(),
            source_id=uuid4(),
            status="running",
        )

        workflow = ClipWorkflow(
            id=run.workflow_id,
            source_id=run.source_id,
            status="discovering",
        )

        source = ClipSource(
            id=run.source_id,
            status="ready_for_discovery",
            transcription_id=uuid4(),
        )

        # Set up mock chain
        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = window

        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source

        # Mock execute to return appropriate results (need extra for _increment_completed_windows and _schedule_next_or_finalizer)
        increment_result = MagicMock()  # For _increment_completed_windows
        schedule_result = MagicMock()  # For _schedule_next_or_finalizer
        execute_results = [window_result, run_result, workflow_result, source_result, increment_result, schedule_result]
        mock_session_factory.execute = AsyncMock(side_effect=execute_results)

        # Mock MediaIndexerClient
        with patch("app.tasks.discovery_tasks.MediaIndexerClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client_class.return_value = mock_client

            # Mock transcription fetch
            mock_transcription = MagicMock()
            mock_transcription.id = source.transcription_id
            mock_transcription.duration_seconds = 300.0
            mock_client.get_transcription = AsyncMock(return_value=mock_transcription)

            # Mock segments fetch - return empty to complete quickly
            mock_page = MagicMock()
            mock_page.items = []
            mock_client.get_transcript_segments = AsyncMock(return_value=mock_page)

            # Mock LiteLLMHTTPDiscoveryProvider
            with patch("app.tasks.discovery_tasks.LiteLLMHTTPDiscoveryProvider"):
                from app.tasks.discovery_tasks import _process_window

                result = await _process_window(window_id, run_id)

                # Window was recovered (attempt_count incremented)
                assert window.attempt_count == 1
                # Window completed (empty segments)
                assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_recently_processing_window_skipped(self, mock_session_factory):
        """Window processing for < 10min is skipped."""
        window_id = uuid4()
        run_id = uuid4()

        # Create window that just started processing
        recent_time = datetime.now(UTC) - timedelta(seconds=60)
        window = DiscoveryWindow(
            id=window_id,
            run_id=run_id,
            window_index=0,
            start_seconds=0,
            end_seconds=300,
            status="processing",
            processing_started_at=recent_time,
        )

        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = window
        mock_session_factory.execute = AsyncMock(return_value=window_result)

        from app.tasks.discovery_tasks import _process_window

        result = await _process_window(window_id, run_id)

        assert result["status"] == "already_processing"
        assert result["window_id"] == str(window_id)


class TestProcessWindowIdempotency:
    """Tests for idempotent window processing."""

    @pytest.mark.asyncio
    async def test_completed_window_schedules_next(self, mock_session_factory):
        """Already completed window schedules next window."""
        window_id = uuid4()
        run_id = uuid4()

        window = DiscoveryWindow(
            id=window_id,
            run_id=run_id,
            window_index=0,
            start_seconds=0,
            end_seconds=300,
            status="completed",
        )

        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = window
        mock_session_factory.execute = AsyncMock(return_value=window_result)

        with patch("app.tasks.discovery_tasks._schedule_next_or_finalizer") as mock_schedule:
            mock_schedule.return_value = None

            from app.tasks.discovery_tasks import _process_window

            result = await _process_window(window_id, run_id)

            assert result["status"] == "already_completed"
            # Verify schedule_next was called
            mock_schedule.assert_called_once()


class TestScheduleNextOrFinalizer:
    """Tests for cascading scheduling logic."""

    @pytest.mark.asyncio
    async def test_schedules_next_pending_window(self, mock_session):
        """Schedules next pending window when available."""
        run_id = uuid4()

        next_window = DiscoveryWindow(
            id=uuid4(),
            run_id=run_id,
            window_index=1,
            start_seconds=300,
            end_seconds=600,
            status="pending",
        )

        result = MagicMock()
        result.scalar_one_or_none.return_value = next_window
        mock_session.execute = AsyncMock(return_value=result)

        with patch("app.tasks.discovery_tasks.process_window") as mock_process:
            mock_process.delay = MagicMock()

            await _schedule_next_or_finalizer(mock_session, run_id)

            mock_process.delay.assert_called_once_with(
                str(next_window.id), str(run_id)
            )

    @pytest.mark.asyncio
    async def test_schedules_finalizer_when_all_done(self, mock_session):
        """Schedules finalizer when no pending windows remain."""
        run_id = uuid4()

        # No pending windows
        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = None

        # Run with all windows done
        run = DiscoveryRun(
            id=run_id,
            total_windows=2,
            completed_windows=1,
            failed_windows=1,
        )
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        mock_session.execute = AsyncMock(side_effect=[window_result, run_result])

        with patch("app.tasks.discovery_tasks.finalize_discovery") as mock_finalize:
            mock_finalize.delay = MagicMock()

            await _schedule_next_or_finalizer(mock_session, run_id)

            mock_finalize.delay.assert_called_once_with(str(run_id))

    @pytest.mark.asyncio
    async def test_no_action_when_windows_in_progress(self, mock_session):
        """No action when windows still processing."""
        run_id = uuid4()

        # No pending windows
        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = None

        # Run with windows still processing
        run = DiscoveryRun(
            id=run_id,
            total_windows=3,
            completed_windows=1,
            failed_windows=0,
        )
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        mock_session.execute = AsyncMock(side_effect=[window_result, run_result])

        with patch("app.tasks.discovery_tasks.finalize_discovery") as mock_finalize:
            mock_finalize.delay = MagicMock()

            await _schedule_next_or_finalizer(mock_session, run_id)

            # Finalizer NOT called because not all windows done
            mock_finalize.delay.assert_not_called()


class TestProcessWindowFailure:
    """Tests for window processing failure handling."""

    @pytest.mark.asyncio
    async def test_source_not_found_marks_window_failed(self, mock_session_factory, mock_settings):
        """Missing source marks window as failed."""
        window_id = uuid4()
        run_id = uuid4()

        window = DiscoveryWindow(
            id=window_id,
            run_id=run_id,
            window_index=0,
            start_seconds=0,
            end_seconds=300,
            status="pending",
        )

        run = DiscoveryRun(
            id=run_id,
            workflow_id=uuid4(),
            source_id=uuid4(),
            status="running",
        )

        workflow = ClipWorkflow(
            id=run.workflow_id,
            source_id=run.source_id,
            status="discovering",
        )

        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = window

        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = None  # Source not found

        execute_results = [window_result, run_result, workflow_result, source_result]
        mock_session_factory.execute = AsyncMock(side_effect=execute_results)

        with patch("app.tasks.discovery_tasks._increment_failed_windows") as mock_increment:
            mock_increment.return_value = None

            with patch("app.tasks.discovery_tasks._schedule_next_or_finalizer") as mock_schedule:
                mock_schedule.return_value = None

                from app.tasks.discovery_tasks import _process_window

                result = await _process_window(window_id, run_id)

                assert result["status"] == "failed"
                assert window.status == "failed"
                assert "Source not found" in window.error_message

    @pytest.mark.asyncio
    async def test_no_transcription_id_marks_window_failed(self, mock_session_factory, mock_settings):
        """Source without transcription_id marks window as failed."""
        window_id = uuid4()
        run_id = uuid4()

        window = DiscoveryWindow(
            id=window_id,
            run_id=run_id,
            window_index=0,
            start_seconds=0,
            end_seconds=300,
            status="pending",
        )

        run = DiscoveryRun(
            id=run_id,
            workflow_id=uuid4(),
            source_id=uuid4(),
            status="running",
        )

        workflow = ClipWorkflow(
            id=run.workflow_id,
            source_id=run.source_id,
            status="discovering",
        )

        source = ClipSource(
            id=run.source_id,
            status="ready_for_discovery",
            transcription_id=None,  # No transcription
        )

        window_result = MagicMock()
        window_result.scalar_one_or_none.return_value = window

        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = run

        workflow_result = MagicMock()
        workflow_result.scalar_one_or_none.return_value = workflow

        source_result = MagicMock()
        source_result.scalar_one_or_none.return_value = source

        execute_results = [window_result, run_result, workflow_result, source_result]
        mock_session_factory.execute = AsyncMock(side_effect=execute_results)

        with patch("app.tasks.discovery_tasks._increment_failed_windows") as mock_increment:
            mock_increment.return_value = None

            with patch("app.tasks.discovery_tasks._schedule_next_or_finalizer") as mock_schedule:
                mock_schedule.return_value = None

                from app.tasks.discovery_tasks import _process_window

                result = await _process_window(window_id, run_id)

                assert result["status"] == "failed"
                assert window.status == "failed"
                assert "transcription_id" in window.error_message
