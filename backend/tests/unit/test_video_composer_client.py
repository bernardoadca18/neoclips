"""Unit tests for VideoComposerClient.

Tests the HTTP client contract with Video Composer API.
"""

import pytest
from uuid import uuid4
from unittest.mock import AsyncMock, patch, MagicMock

from app.clients.video_composer_client import (
    VideoComposerClient,
    VideoComposerAPIError,
    VideoComposerConnectionError,
    VideoComposerTimeoutError,
    RenderJobOut,
    MediaOut,
)


class TestVideoComposerClient:
    """Tests for VideoComposerClient."""

    @pytest.fixture
    def client(self):
        """Create a VideoComposerClient instance."""
        return VideoComposerClient(
            base_url="http://localhost:8001",
            timeout_seconds=30,
        )

    def test_client_initialization(self, client):
        """Client should initialize with correct settings."""
        assert client.base_url == "http://localhost:8001"
        assert client.timeout_seconds == 30

    def test_client_strips_trailing_slash(self):
        """Client should strip trailing slash from base_url."""
        client = VideoComposerClient(base_url="http://localhost:8001/")
        assert client.base_url == "http://localhost:8001"


class TestSubmitRender:
    """Tests for submit_render method."""

    @pytest.fixture
    def client(self):
        """Create a VideoComposerClient instance."""
        return VideoComposerClient(base_url="http://localhost:8001")

    @pytest.mark.asyncio
    async def test_submit_render_success(self, client):
        """Successful render submission should return RenderJobOut."""
        from httpx import Response

        render_id = uuid4()
        source_media_id = uuid4()

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "id": str(render_id),
            "source_media_id": str(source_media_id),
            "status": "pending",
            "progress": 0.0,
            "output_media_id": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-09-03T00:00:00Z",
            "updated_at": "2026-09-03T00:00:00Z",
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await client.submit_render(
                source_media_id=source_media_id,
                start_seconds=10.0,
                end_seconds=30.0,
            )

            assert isinstance(result, RenderJobOut)
            assert result.id == render_id
            assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_submit_render_with_idempotency_key(self, client):
        """Render submission should include idempotency key header."""
        from httpx import Response

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 202
        mock_response.json.return_value = {
            "id": str(uuid4()),
            "source_media_id": str(uuid4()),
            "status": "pending",
            "progress": 0.0,
            "output_media_id": None,
            "error": None,
            "started_at": None,
            "completed_at": None,
            "created_at": "2026-09-03T00:00:00Z",
            "updated_at": "2026-09-03T00:00:00Z",
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            await client.submit_render(
                source_media_id=uuid4(),
                start_seconds=10.0,
                end_seconds=30.0,
                idempotency_key="test-key-123",
            )

            call_kwargs = mock_request.call_args
            assert "Idempotency-Key" in call_kwargs.kwargs["headers"]
            assert call_kwargs.kwargs["headers"]["Idempotency-Key"] == "test-key-123"

    @pytest.mark.asyncio
    async def test_submit_render_api_error(self, client):
        """API error should raise VideoComposerAPIError."""
        from httpx import Response

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(VideoComposerAPIError) as exc_info:
                await client.submit_render(
                    source_media_id=uuid4(),
                    start_seconds=10.0,
                    end_seconds=30.0,
                )

            assert exc_info.value.status_code == 500


class TestGetRenderJob:
    """Tests for get_render_job method."""

    @pytest.fixture
    def client(self):
        """Create a VideoComposerClient instance."""
        return VideoComposerClient(base_url="http://localhost:8001")

    @pytest.mark.asyncio
    async def test_get_render_job_success(self, client):
        """Successful job fetch should return RenderJobOut."""
        from httpx import Response

        render_id = uuid4()

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": str(render_id),
            "source_media_id": str(uuid4()),
            "status": "completed",
            "progress": 1.0,
            "output_media_id": str(uuid4()),
            "error": None,
            "started_at": "2026-09-03T00:00:00Z",
            "completed_at": "2026-09-03T00:01:00Z",
            "created_at": "2026-09-03T00:00:00Z",
            "updated_at": "2026-09-03T00:01:00Z",
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await client.get_render_job(render_id)

            assert isinstance(result, RenderJobOut)
            assert result.id == render_id
            assert result.status == "completed"
            assert result.progress == 1.0

    @pytest.mark.asyncio
    async def test_get_render_job_not_found(self, client):
        """Job not found should raise VideoComposerAPIError with 404."""
        from httpx import Response

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 404

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(VideoComposerAPIError) as exc_info:
                await client.get_render_job(uuid4())

            assert exc_info.value.status_code == 404


class TestGetMedia:
    """Tests for get_media method."""

    @pytest.fixture
    def client(self):
        """Create a VideoComposerClient instance."""
        return VideoComposerClient(base_url="http://localhost:8001")

    @pytest.mark.asyncio
    async def test_get_media_success(self, client):
        """Successful media fetch should return MediaOut."""
        from httpx import Response

        media_id = uuid4()

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": str(media_id),
            "storage_uri": "s3://bucket/output.mp4",
            "original_filename": "output.mp4",
            "content_type": "video/mp4",
            "byte_size": 1024000,
            "sha256": "abc123",
            "duration_seconds": 20.0,
            "width": 1080,
            "height": 1920,
        }

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await client.get_media(media_id)

            assert isinstance(result, MediaOut)
            assert result.id == media_id
            assert result.duration_seconds == 20.0
            assert result.width == 1080
            assert result.height == 1920

    @pytest.mark.asyncio
    async def test_get_media_not_found(self, client):
        """Media not found should raise VideoComposerAPIError with 404."""
        from httpx import Response

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 404

        with patch.object(client, "_request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            with pytest.raises(VideoComposerAPIError) as exc_info:
                await client.get_media(uuid4())

            assert exc_info.value.status_code == 404


class TestHealthCheck:
    """Tests for health_check method."""

    @pytest.fixture
    def client(self):
        """Create a VideoComposerClient instance."""
        return VideoComposerClient(base_url="http://localhost:8001")

    @pytest.mark.asyncio
    async def test_health_check_success(self, client):
        """Successful health check should return True."""
        from httpx import Response, AsyncClient

        mock_response = MagicMock(spec=Response)
        mock_response.status_code = 200

        with patch.object(AsyncClient, "__aenter__") as mock_enter:
            mock_client = MagicMock(spec=AsyncClient)
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_enter.return_value = mock_client

            result = await client.health_check()
            assert result is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self, client):
        """Failed health check should return False."""
        with patch.object(client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = Exception("Connection refused")

            result = await client.health_check()
            assert result is False


class TestErrorHandling:
    """Tests for error handling."""

    @pytest.fixture
    def client(self):
        """Create a VideoComposerClient instance."""
        return VideoComposerClient(base_url="http://localhost:8001")

    @pytest.mark.asyncio
    async def test_connection_error(self, client):
        """Connection error should raise VideoComposerConnectionError."""
        import httpx

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_get_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_get_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(VideoComposerConnectionError):
                await client._request("GET", "/test")

    @pytest.mark.asyncio
    async def test_timeout_error(self, client):
        """Timeout error should raise VideoComposerTimeoutError."""
        import httpx

        with patch.object(client, "_get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_get_client.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_get_client.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(VideoComposerTimeoutError):
                await client._request("GET", "/test")
