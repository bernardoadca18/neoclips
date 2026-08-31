"""Tests for Stage 3.2 Discovery endpoints."""

import hashlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import TranscriptionOut
from app.core.database import get_session
from app.main import app
from app.models.entities import ClipSource, ClipWorkflow, DiscoveryRun, DiscoveryWindow


@pytest.fixture
def mock_media_indexer_client():
    """Create a mock MediaIndexerClient."""
    with patch("app.api.routers.discovery.MediaIndexerClient") as mock:
        client_instance = MagicMock()
        mock.return_value = client_instance
        yield client_instance


@pytest.fixture
def sample_transcription():
    """Create a sample transcription response."""
    return TranscriptionOut(
        id=uuid4(),
        project_id=uuid4(),
        session_id=uuid4(),
        media_id=uuid4(),
        provider="test_provider",
        model="test_model",
        status="completed",
        language_requested="en",
        language_detected="en",
        duration_seconds=1800.0,  # 30 minutes
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
async def client_with_session(session: AsyncSession):
    """Create an async client with session dependency override."""
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
async def setup_workflow_ready_for_discovery(session: AsyncSession):
    """Create a workflow with source ready for discovery."""
    source = ClipSource(
        id=uuid4(),
        status="ready_for_discovery",
        mode="safe_automated",
        transcription_id=uuid4(),
        creator="Test Creator",
        program="Test Program",
        title="Test Video",
    )
    session.add(source)
    await session.flush()

    workflow = ClipWorkflow(
        id=uuid4(),
        source_id=source.id,
        status="created",
    )
    session.add(workflow)
    await session.commit()

    return workflow, source


class TestDiscoveryEndpointLocation:
    """Tests for the new endpoint location."""

    @pytest.mark.asyncio
    async def test_discover_endpoint_at_workflows_path(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, sample_transcription, client_with_session
    ):
        """Test that discovery endpoint is at /v1/workflows/{workflow_id}/discover."""
        workflow, source = setup_workflow_ready_for_discovery

        # Mock the transcription response
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=sample_transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["workflow_id"] == str(workflow.id)
        assert data["status"] == "running"


class TestDurationBasedWindows:
    """Tests for duration-based window creation."""

    @pytest.mark.asyncio
    async def test_windows_created_by_duration_not_segments(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, client_with_session
    ):
        """Test that windows are created based on transcription duration, not segment count."""
        workflow, source = setup_workflow_ready_for_discovery

        # Create a transcription with 30 minutes duration
        transcription = TranscriptionOut(
            id=source.transcription_id,
            project_id=uuid4(),
            session_id=uuid4(),
            media_id=uuid4(),
            provider="test_provider",
            model="test_model",
            status="completed",
            language_requested="en",
            language_detected="en",
            duration_seconds=1800.0,  # 30 minutes
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()

        # With 300s windows and 60s overlap, 1800s should create ~7 windows
        # effective_window_size = 300 - 60 = 240
        # window_count = ceil((1800 - 60) / 240) = ceil(1740/240) = ceil(7.25) = 8
        assert data["total_windows"] >= 7
        assert data["total_windows"] <= 9

    @pytest.mark.asyncio
    async def test_windows_for_short_transcription(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, client_with_session
    ):
        """Test that short transcription creates at least one window."""
        workflow, source = setup_workflow_ready_for_discovery

        # Create a short transcription
        transcription = TranscriptionOut(
            id=source.transcription_id,
            project_id=uuid4(),
            session_id=uuid4(),
            media_id=uuid4(),
            provider="test_provider",
            model="test_model",
            status="completed",
            language_requested="en",
            language_detected="en",
            duration_seconds=60.0,  # 1 minute
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["total_windows"] >= 1


class TestIdempotencyWithConflict:
    """Tests for idempotency with 409 Conflict handling."""

    @pytest.mark.asyncio
    async def test_same_idempotency_key_same_config_returns_existing(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, sample_transcription, client_with_session
    ):
        """Test that same idempotency key with same config returns existing run."""
        workflow, source = setup_workflow_ready_for_discovery
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=sample_transcription)

        idempotency_key = "test-key-123"

        # First request
        response1 = await client_with_session.post(
            f"/v1/discovery/workflows/{workflow.id}/discover",
            headers={"Idempotency-Key": idempotency_key},
        )

        # Second request with same key
        response2 = await client_with_session.post(
            f"/v1/discovery/workflows/{workflow.id}/discover",
            headers={"Idempotency-Key": idempotency_key},
        )

        assert response1.status_code == status.HTTP_201_CREATED
        assert response2.status_code == status.HTTP_201_CREATED
        assert response1.json()["id"] == response2.json()["id"]

    @pytest.mark.asyncio
    async def test_same_idempotency_key_different_config_returns_409(
        self, session: AsyncSession, mock_media_indexer_client, sample_transcription, client_with_session
    ):
        """Test that same idempotency key with different config returns 409."""
        # Create first workflow
        source1 = ClipSource(
            id=uuid4(),
            status="ready_for_discovery",
            mode="safe_automated",
            transcription_id=uuid4(),
        )
        session.add(source1)
        await session.flush()

        workflow1 = ClipWorkflow(
            id=uuid4(),
            source_id=source1.id,
            status="created",
        )
        session.add(workflow1)

        # Create second workflow with different transcription
        source2 = ClipSource(
            id=uuid4(),
            status="ready_for_discovery",
            mode="safe_automated",
            transcription_id=uuid4(),  # Different transcription
        )
        session.add(source2)
        await session.flush()

        workflow2 = ClipWorkflow(
            id=uuid4(),
            source_id=source2.id,
            status="created",
        )
        session.add(workflow2)
        await session.commit()

        # Create transcriptions with different IDs
        transcription1 = TranscriptionOut(
            id=source1.transcription_id,
            project_id=uuid4(),
            session_id=uuid4(),
            media_id=uuid4(),
            provider="test_provider",
            model="test_model",
            status="completed",
            language_requested="en",
            language_detected="en",
            duration_seconds=1800.0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        transcription2 = TranscriptionOut(
            id=source2.transcription_id,
            project_id=uuid4(),
            session_id=uuid4(),
            media_id=uuid4(),
            provider="test_provider",
            model="test_model",
            status="completed",
            language_requested="en",
            language_detected="en",
            duration_seconds=1800.0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )

        mock_media_indexer_client.get_transcription = AsyncMock(side_effect=[transcription1, transcription2])

        idempotency_key = "test-key-conflict"

        # First request
        response1 = await client_with_session.post(
            f"/v1/discovery/workflows/{workflow1.id}/discover",
            headers={"Idempotency-Key": idempotency_key},
        )

        # Second request with same key but different source (different config)
        response2 = await client_with_session.post(
            f"/v1/discovery/workflows/{workflow2.id}/discover",
            headers={"Idempotency-Key": idempotency_key},
        )

        assert response1.status_code == status.HTTP_201_CREATED
        assert response2.status_code == status.HTTP_409_CONFLICT


class TestWorkflowTransitions:
    """Tests for ClipWorkflow state transitions."""

    @pytest.mark.asyncio
    async def test_workflow_transitions_to_discovering(
        self, session: AsyncSession, setup_workflow_ready_for_discovery, mock_media_indexer_client, sample_transcription, client_with_session
    ):
        """Test that workflow transitions from created to discovering."""
        workflow, source = setup_workflow_ready_for_discovery
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=sample_transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_201_CREATED

        # Verify workflow status changed
        result = await session.execute(select(ClipWorkflow).where(ClipWorkflow.id == workflow.id))
        updated_workflow = result.scalar_one()
        assert updated_workflow.status == "discovering"


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_workflow_not_found(self, client_with_session):
        """Test 404 when workflow doesn't exist."""
        fake_workflow_id = uuid4()

        response = await client_with_session.post(f"/v1/discovery/workflows/{fake_workflow_id}/discover")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_source_not_ready_for_discovery(self, session: AsyncSession, client_with_session):
        """Test 400 when source is not ready for discovery."""
        source = ClipSource(
            id=uuid4(),
            status="pending",  # Not ready
            mode="safe_automated",
        )
        session.add(source)
        await session.flush()

        workflow = ClipWorkflow(
            id=uuid4(),
            source_id=source.id,
            status="created",
        )
        session.add(workflow)
        await session.commit()

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "must be ready_for_discovery" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_source_without_transcription(self, session: AsyncSession, client_with_session):
        """Test 400 when source has no transcription_id."""
        source = ClipSource(
            id=uuid4(),
            status="ready_for_discovery",
            mode="safe_automated",
            transcription_id=None,  # No transcription
        )
        session.add(source)
        await session.flush()

        workflow = ClipWorkflow(
            id=uuid4(),
            source_id=source.id,
            status="created",
        )
        session.add(workflow)
        await session.commit()

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "no transcription_id" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_transcription_without_duration(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, client_with_session
    ):
        """Test 400 when transcription has no valid duration."""
        workflow, source = setup_workflow_ready_for_discovery

        transcription = TranscriptionOut(
            id=source.transcription_id,
            project_id=uuid4(),
            session_id=uuid4(),
            media_id=uuid4(),
            provider="test_provider",
            model="test_model",
            status="completed",
            language_requested="en",
            language_detected="en",
            duration_seconds=None,  # No duration
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "no valid duration" in response.json()["detail"]


class TestCanonicalFingerprint:
    """Tests for canonical fingerprint computation."""

    @pytest.mark.asyncio
    async def test_fingerprint_based_on_source_state(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, sample_transcription, client_with_session
    ):
        """Test that fingerprint is computed from source state."""
        workflow, source = setup_workflow_ready_for_discovery
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=sample_transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["request_fingerprint"] is not None

        # Verify fingerprint is SHA-256 hex digest (64 characters)
        assert len(data["request_fingerprint"]) == 64


class TestBootstrapScheduling:
    """Tests for bootstrap scheduling (only first window)."""

    @pytest.mark.asyncio
    async def test_only_first_window_scheduled_at_bootstrap(
        self, setup_workflow_ready_for_discovery, mock_media_indexer_client, sample_transcription, client_with_session
    ):
        """Test that only the first pending window is scheduled at bootstrap."""
        workflow, source = setup_workflow_ready_for_discovery
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=sample_transcription)

        with patch("app.tasks.discovery_tasks.process_window") as mock_process_window:
            mock_process_window.delay = MagicMock()

            response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

            assert response.status_code == status.HTTP_201_CREATED

            # Verify process_window.delay was called exactly once (for first window)
            assert mock_process_window.delay.call_count == 1


class TestWindowOverlap:
    """Tests for window overlap configuration."""

    @pytest.mark.asyncio
    async def test_windows_have_overlap(
        self, session: AsyncSession, setup_workflow_ready_for_discovery, mock_media_indexer_client, client_with_session
    ):
        """Test that windows overlap correctly."""
        workflow, source = setup_workflow_ready_for_discovery

        # Create a 20-minute transcription
        transcription = TranscriptionOut(
            id=source.transcription_id,
            project_id=uuid4(),
            session_id=uuid4(),
            media_id=uuid4(),
            provider="test_provider",
            model="test_model",
            status="completed",
            language_requested="en",
            language_detected="en",
            duration_seconds=1200.0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        mock_media_indexer_client.get_transcription = AsyncMock(return_value=transcription)

        response = await client_with_session.post(f"/v1/discovery/workflows/{workflow.id}/discover")

        assert response.status_code == status.HTTP_201_CREATED
        run_id = response.json()["id"]

        # Get windows from database
        result = await session.execute(
            select(DiscoveryWindow).where(DiscoveryWindow.run_id == run_id).order_by(DiscoveryWindow.window_index)
        )
        windows = result.scalars().all()

        # Verify overlap: second window start should be before first window end
        if len(windows) >= 2:
            # Window duration is 300s, overlap is 60s
            # So effective step is 240s
            # Window 0: 0-300
            # Window 1: 240-540 (starts at 240, which is before 300)
            assert windows[1].start_seconds < windows[0].end_seconds
