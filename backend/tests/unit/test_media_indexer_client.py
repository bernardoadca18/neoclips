"""Unit tests for MediaIndexerClient using httpx.MockTransport."""

import io
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from app.clients.media_indexer_client import (
    MediaIndexerAPIError,
    MediaIndexerClient,
    MediaIndexerConnectionError,
    MediaIndexerTimeoutError,
)


def make_mock_transport(status_code: int, json_data: dict | None = None, text: str = "") -> httpx.MockTransport:
    """Create a mock transport for testing."""
    response_body = b""
    if json_data is not None:
        import json
        response_body = json.dumps(json_data).encode()
    else:
        response_body = text.encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=response_body)

    return httpx.MockTransport(handler)


def make_session_ingest_response(project_id, session_id, media_id, job_id):
    """Create a valid SessionIngestOut response."""
    now = datetime.now(UTC).isoformat()
    return {
        "session": {
            "id": str(session_id),
            "project_id": str(project_id),
            "media_id": str(media_id),
            "label": "test video",
            "status": "created",
            "created_at": now,
            "media": {
                "id": str(media_id),
                "storage_uri": "file:///test/video.mp4",
                "original_filename": "test.mp4",
                "content_type": "video/mp4",
                "byte_size": 1000,
                "sha256": "abc123",
            },
        },
        "job": {
            "id": str(job_id),
            "project_id": str(project_id),
            "session_id": str(session_id),
            "media_id": str(media_id),
            "job_type": "initial_index",
            "status": "pending",
            "stage": "queued",
            "progress": 0.0,
            "attempt_count": 0,
            "max_attempts": 3,
            "created_at": now,
            "updated_at": now,
        },
    }


class TestMediaIndexerClientIngestVideo:
    """Tests for ingest_video method - multipart form upload."""

    def test_ingest_video_success(self) -> None:
        """Test successful video ingest returns session and job."""
        project_id = uuid4()
        media_id = uuid4()
        session_id = uuid4()
        job_id = uuid4()

        # Mock project resolution and ingest response
        project_response = {"id": str(project_id), "name": "NeoClips Managed Sources", "created_at": datetime.now(UTC).isoformat()}

        ingest_response = make_session_ingest_response(project_id, session_id, media_id, job_id)

        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            if "projects" in request.url.path and request.method == "GET":
                return httpx.Response(200, json=[project_response])
            if "sessions" in request.url.path and request.method == "POST":
                return httpx.Response(201, json=ingest_response)
            return httpx.Response(404)

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test", project_name="NeoClips Managed Sources")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            # Create a file-like object for streaming
            video_file = io.BytesIO(b"fake video content")
            video_file.name = "test.mp4"

            result = await client.ingest_video(video_file, "test video")

            assert result.session.id == session_id
            assert result.job.id == job_id
            assert result.session.media_id == media_id
            # Should only make 2 calls: project resolution + ingest
            assert call_count[0] == 2

        asyncio.run(run_test())

    def test_ingest_video_connection_error_no_retry(self) -> None:
        """Test that connection errors are raised, not retried internally."""
        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            raise httpx.ConnectError("Connection refused")

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test", project_name="NeoClips Managed Sources")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            video_file = io.BytesIO(b"test")
            video_file.name = "test.mp4"

            with pytest.raises(MediaIndexerConnectionError):
                await client.ingest_video(video_file, "test video")

            # Should only attempt once - no internal retry
            assert call_count[0] == 1

        asyncio.run(run_test())

    def test_ingest_video_timeout_no_retry(self) -> None:
        """Test that timeouts are raised, not retried internally."""
        call_count = [0]

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            raise httpx.TimeoutException("Request timed out")

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test", project_name="NeoClips Managed Sources")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            video_file = io.BytesIO(b"test")
            video_file.name = "test.mp4"

            with pytest.raises(MediaIndexerTimeoutError):
                await client.ingest_video(video_file, "test video")

            # Should only attempt once - no internal retry
            assert call_count[0] == 1

        asyncio.run(run_test())

    def test_ingest_video_api_error_propagated(self) -> None:
        """Test that API errors are raised with status code."""
        project_id = uuid4()

        def handler(request: httpx.Request) -> httpx.Response:
            if "projects" in request.url.path and request.method == "GET":
                return httpx.Response(200, json=[{"id": str(project_id), "name": "NeoClips Managed Sources"}])
            if "sessions" in request.url.path and request.method == "POST":
                return httpx.Response(500, json={"error": "Internal server error"})
            return httpx.Response(404)

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test", project_name="NeoClips Managed Sources")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            video_file = io.BytesIO(b"test")
            video_file.name = "test.mp4"

            with pytest.raises(MediaIndexerAPIError) as exc_info:
                await client.ingest_video(video_file, "test video")

            assert exc_info.value.status_code == 500

        asyncio.run(run_test())


class TestMediaIndexerClientGetJob:
    """Tests for get_job method - one-shot call for polling."""

    def test_get_job_success(self) -> None:
        """Test successful job fetch."""
        job_id = uuid4()
        session_id = uuid4()
        media_id = uuid4()
        project_id = uuid4()
        now = datetime.now(UTC).isoformat()

        job_response = {
            "id": str(job_id),
            "project_id": str(project_id),
            "session_id": str(session_id),
            "media_id": str(media_id),
            "job_type": "initial_index",
            "status": "running",
            "stage": "processing",
            "progress": 0.5,
            "attempt_count": 0,
            "max_attempts": 3,
            "created_at": now,
            "updated_at": now,
        }

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(200, json_data=job_response)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            result = await client.get_job(job_id)

            assert result.id == job_id
            assert result.status == "running"
            assert result.progress == 0.5

        asyncio.run(run_test())

    def test_get_job_not_found(self) -> None:
        """Test job not found raises API error."""
        job_id = uuid4()

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(404, text="Not found")
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            with pytest.raises(MediaIndexerAPIError) as exc_info:
                await client.get_job(job_id)

            assert exc_info.value.status_code == 404

        asyncio.run(run_test())

    def test_get_job_one_shot_no_polling(self) -> None:
        """Test that get_job makes exactly one call."""
        call_count = [0]
        job_id = uuid4()
        now = datetime.now(UTC).isoformat()

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, json={
                "id": str(job_id),
                "project_id": str(uuid4()),
                "session_id": str(uuid4()),
                "media_id": str(uuid4()),
                "job_type": "initial_index",
                "status": "processing",
                "stage": "processing",
                "progress": 0.3,
                "attempt_count": 0,
                "max_attempts": 3,
                "created_at": now,
                "updated_at": now,
            })

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            await client.get_job(job_id)

            # Exactly one call - polling is done by Celery tasks
            assert call_count[0] == 1

        asyncio.run(run_test())


class TestMediaIndexerClientGetSession:
    """Tests for get_session method - one-shot call for polling."""

    def test_get_session_success(self) -> None:
        """Test successful session fetch."""
        session_id = uuid4()
        media_id = uuid4()
        project_id = uuid4()

        session_response = {
            "id": str(session_id),
            "project_id": str(project_id),
            "media_id": str(media_id),
            "label": "test session",
            "status": "indexed",
            "created_at": datetime.now(UTC).isoformat(),
        }

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(200, json_data=session_response)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            result = await client.get_session(session_id)

            assert result.id == session_id
            assert result.status == "indexed"

        asyncio.run(run_test())

    def test_get_session_not_found(self) -> None:
        """Test session not found raises API error."""
        session_id = uuid4()

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(404, text="Not found")
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            with pytest.raises(MediaIndexerAPIError) as exc_info:
                await client.get_session(session_id)

            assert exc_info.value.status_code == 404

        asyncio.run(run_test())


class TestMediaIndexerClientGetTranscription:
    """Tests for get_transcription method - one-shot call for polling."""

    def test_get_transcription_success(self) -> None:
        """Test successful transcription fetch."""
        transcription_id = uuid4()
        session_id = uuid4()
        project_id = uuid4()
        media_id = uuid4()

        transcription_response = {
            "id": str(transcription_id),
            "project_id": str(project_id),
            "session_id": str(session_id),
            "media_id": str(media_id),
            "provider": "whisper",
            "model": "large-v3",
            "status": "completed",
            "duration_seconds": 120.5,
            "created_at": datetime.now(UTC).isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(200, json_data=transcription_response)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            result = await client.get_transcription(transcription_id)

            assert result.id == transcription_id
            assert result.status == "completed"
            assert result.duration_seconds == 120.5

        asyncio.run(run_test())


class TestMediaIndexerClientGetTranscriptSegments:
    """Tests for get_transcript_segments method."""

    def test_get_transcript_segments_success(self) -> None:
        """Test successful transcript segments fetch with pagination."""
        transcription_id = uuid4()

        segments_response = {
            "items": [
                {
                    "id": str(uuid4()),
                    "transcription_id": str(transcription_id),
                    "sequence": 0,
                    "start_seconds": 0.0,
                    "end_seconds": 5.0,
                    "text": "Hello world",
                },
                {
                    "id": str(uuid4()),
                    "transcription_id": str(transcription_id),
                    "sequence": 1,
                    "start_seconds": 5.0,
                    "end_seconds": 10.0,
                    "text": "This is a test",
                },
            ],
            "total": 2,
            "offset": 0,
            "limit": 500,
        }

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(200, json_data=segments_response)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            result = await client.get_transcript_segments(transcription_id)

            assert result.total == 2
            assert len(result.items) == 2
            assert result.items[0].text == "Hello world"

        asyncio.run(run_test())


class TestMediaIndexerClientTriggerTranscription:
    """Tests for trigger_transcription method."""

    def test_trigger_transcription_success(self) -> None:
        """Test successful transcription trigger."""
        session_id = uuid4()
        transcription_id = uuid4()
        job_id = uuid4()
        project_id = uuid4()
        media_id = uuid4()
        now = datetime.now(UTC).isoformat()

        transcription_response = {
            "transcription": {
                "id": str(transcription_id),
                "project_id": str(project_id),
                "session_id": str(session_id),
                "media_id": str(media_id),
                "provider": "whisper",
                "model": "large-v3",
                "status": "pending",
                "created_at": now,
                "updated_at": now,
            },
            "job": {
                "id": str(job_id),
                "project_id": str(project_id),
                "session_id": str(session_id),
                "media_id": str(media_id),
                "job_type": "transcription",
                "status": "pending",
                "stage": "queued",
                "progress": 0.0,
                "attempt_count": 0,
                "max_attempts": 3,
                "created_at": now,
                "updated_at": now,
            },
            "created": True,
        }

        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(201, json_data=transcription_response)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            result = await client.trigger_transcription(session_id)

            assert result.transcription.id == transcription_id
            assert result.job.id == job_id
            assert result.created is True

        asyncio.run(run_test())


class TestMediaIndexerClientHealthCheck:
    """Tests for health_check method."""

    def test_health_check_healthy(self) -> None:
        """Test health check returns True for 200."""
        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(200)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda **_kw: httpx.AsyncClient(transport=transport)

            result = await client.health_check()

            assert result is True

        asyncio.run(run_test())

    def test_health_check_unhealthy(self) -> None:
        """Test health check returns False for non-200."""
        import asyncio

        async def run_test() -> None:
            transport = make_mock_transport(503)
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda **_kw: httpx.AsyncClient(transport=transport)

            result = await client.health_check()

            assert result is False

        asyncio.run(run_test())


class TestMediaIndexerClientNoWaitMethods:
    """Verify that wait_for_* methods do NOT exist."""

    def test_no_wait_for_initial_index(self) -> None:
        """Client should not have wait_for_initial_index method."""
        client = MediaIndexerClient()
        assert not hasattr(client, "wait_for_initial_index")

    def test_no_wait_for_transcription(self) -> None:
        """Client should not have wait_for_transcription method."""
        client = MediaIndexerClient()
        assert not hasattr(client, "wait_for_transcription")
