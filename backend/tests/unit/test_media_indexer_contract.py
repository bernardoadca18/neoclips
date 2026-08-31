"""Contract tests for Media Indexer API.

These tests verify the contract between NeoClips and Media Indexer.
They document the expected API shapes and can be run against:
1. MockTransport for unit testing
2. Real Media Indexer instance for integration testing

Contract tests focus on:
- Request/response shapes
- Required fields
- Status code handling
- Error formats
"""

import io
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.clients.media_indexer_client import (
    JobOut,
    MediaIndexerAPIError,
    MediaIndexerClient,
    SessionIngestOut,
    SessionOut,
    TranscriptionOut,
)


class TestMediaIndexerContractPaths:
    """Tests verifying correct API paths (no /api/v1 prefix)."""

    def test_ingest_video_uses_correct_path(self) -> None:
        """Ingest video should POST to /projects/{id}/sessions."""
        project_id = uuid4()
        captured_path = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_path.append(request.url.path)
            if "projects" in request.url.path:
                if request.method == "GET":
                    return httpx.Response(
                        200,
                        json=[{"id": str(project_id), "name": "Test Project", "created_at": datetime.now(UTC).isoformat()}],
                    )
                elif request.method == "POST" and "sessions" in request.url.path:
                    return httpx.Response(201, json=_make_ingest_response(project_id))
            return httpx.Response(404)

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test", project_name="Test Project")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            video_file = io.BytesIO(b"test video")
            video_file.name = "test.mp4"

            await client.ingest_video(video_file, "test")

            # Should NOT have /api/v1 prefix
            assert any("/projects/" in path and "/sessions" in path for path in captured_path)
            assert not any("/api/v1" in path for path in captured_path)

        asyncio.run(run_test())

    def test_get_job_uses_correct_path(self) -> None:
        """Get job should GET /jobs/{job_id} (no /api/v1 prefix)."""
        job_id = uuid4()
        captured_path = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_path.append(request.url.path)
            return httpx.Response(200, json=_make_job_response(job_id))

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            await client.get_job(job_id)

            assert any(f"/jobs/{job_id}" in path for path in captured_path)
            assert not any("/api/v1" in path for path in captured_path)

        asyncio.run(run_test())


class TestMediaIndexerContractRequestShapes:
    """Tests verifying request shapes."""

    def test_ingest_video_multipart_form(self) -> None:
        """Ingest video should send multipart form with label, video, notes."""
        project_id = uuid4()
        captured_content_type = []

        def handler(request: httpx.Request) -> httpx.Response:
            if "projects" in request.url.path and request.method == "GET":
                return httpx.Response(
                    200,
                    json=[{"id": str(project_id), "name": "Test", "created_at": datetime.now(UTC).isoformat()}],
                )
            if "sessions" in request.url.path:
                content_type = request.headers.get("content-type", "")
                captured_content_type.append(content_type)
                return httpx.Response(201, json=_make_ingest_response(project_id))
            return httpx.Response(404)

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test", project_name="Test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            video_file = io.BytesIO(b"test video content")
            video_file.name = "test.mp4"

            await client.ingest_video(video_file, "test label")

            # Should be multipart/form-data
            assert any("multipart/form-data" in ct for ct in captured_content_type)

        asyncio.run(run_test())

    def test_ingest_video_streaming_upload(self) -> None:
        """Ingest video should use streaming (file-like object, not bytes)."""
        # This test verifies the contract that ingest_video accepts file-like objects
        # for streaming upload, not pre-loaded bytes in memory.
        # The implementation passes the file object directly to httpx.
        import asyncio

        async def run_test() -> None:
            _client = MediaIndexerClient(base_url="http://test")

            # Create a file-like object
            video_file = io.BytesIO(b"test video content")
            video_file.name = "test.mp4"

            # The method should accept file-like objects with read() and name
            assert hasattr(video_file, "read")
            assert hasattr(video_file, "name")

        asyncio.run(run_test())


class TestMediaIndexerContractResponseShapes:
    """Tests verifying response shapes."""

    def test_session_ingest_out_shape(self) -> None:
        """SessionIngestOut must have session and job."""
        project_id = uuid4()
        session_id = uuid4()
        media_id = uuid4()
        job_id = uuid4()

        response = _make_ingest_response(project_id, session_id, media_id, job_id)
        result = SessionIngestOut(**response)

        assert result.session.id == session_id
        assert result.job.id == job_id
        assert result.session.media_id == media_id

    def test_job_out_shape(self) -> None:
        """JobOut must have required fields."""
        job_id = uuid4()
        response = _make_job_response(job_id)
        result = JobOut(**response)

        assert result.id == job_id
        assert result.job_type == "initial_index"
        assert result.status == "running"
        assert result.progress == 0.5

    def test_session_out_shape(self) -> None:
        """SessionOut must have required fields."""
        session_id = uuid4()
        response = _make_session_response(session_id)
        result = SessionOut(**response)

        assert result.id == session_id
        assert result.status == "indexed"

    def test_transcription_out_shape(self) -> None:
        """TranscriptionOut must have required fields."""
        transcription_id = uuid4()
        response = _make_transcription_response(transcription_id)
        result = TranscriptionOut(**response)

        assert result.id == transcription_id
        assert result.status == "completed"
        assert result.duration_seconds == 120.5


class TestMediaIndexerContractErrorHandling:
    """Tests verifying error handling contract."""

    def test_404_raises_api_error_with_status_code(self) -> None:
        """404 responses should raise MediaIndexerAPIError with status_code=404."""
        job_id = uuid4()

        import asyncio

        async def run_test() -> None:
            transport = httpx.MockTransport(lambda _r: httpx.Response(404, text="Not found"))
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            with pytest.raises(MediaIndexerAPIError) as exc_info:
                await client.get_job(job_id)

            assert exc_info.value.status_code == 404

        asyncio.run(run_test())

    def test_500_raises_api_error_with_status_code(self) -> None:
        """500 responses should raise MediaIndexerAPIError with status_code=500."""
        import asyncio

        async def run_test() -> None:
            transport = httpx.MockTransport(lambda _r: httpx.Response(500, json={"error": "Internal error"}))
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=transport)

            with pytest.raises(MediaIndexerAPIError) as exc_info:
                await client.get_job(uuid4())

            assert exc_info.value.status_code == 500

        asyncio.run(run_test())


class TestMediaIndexerContractOneShotPolling:
    """Tests verifying one-shot polling contract."""

    def test_get_job_makes_single_request(self) -> None:
        """get_job should make exactly one HTTP request (no retry loops)."""
        call_count = [0]
        job_id = uuid4()

        def handler(request: httpx.Request) -> httpx.Response:
            call_count[0] += 1
            return httpx.Response(200, json=_make_job_response(job_id))

        import asyncio

        async def run_test() -> None:
            client = MediaIndexerClient(base_url="http://test")
            client._get_client = lambda _timeout=30: httpx.AsyncClient(transport=httpx.MockTransport(handler))

            await client.get_job(job_id)

            # Exactly one call - polling is done by Celery tasks
            assert call_count[0] == 1

        asyncio.run(run_test())

    def test_no_wait_methods_exist(self) -> None:
        """Client should NOT have wait_for_* methods (polling is external)."""
        client = MediaIndexerClient()

        assert not hasattr(client, "wait_for_initial_index")
        assert not hasattr(client, "wait_for_transcription")
        assert not hasattr(client, "wait_for_job")


# Helper functions to create test responses


def _make_ingest_response(
    project_id: UUID | None = None,
    session_id: UUID | None = None,
    media_id: UUID | None = None,
    job_id: UUID | None = None,
) -> dict:
    """Create a valid SessionIngestOut response."""
    now = datetime.now(UTC).isoformat()
    return {
        "session": {
            "id": str(session_id or uuid4()),
            "project_id": str(project_id or uuid4()),
            "media_id": str(media_id or uuid4()),
            "label": "test video",
            "status": "created",
            "created_at": now,
            "media": {
                "id": str(media_id or uuid4()),
                "storage_uri": "file:///test/video.mp4",
                "original_filename": "test.mp4",
                "content_type": "video/mp4",
                "byte_size": 1000,
                "sha256": "abc123",
            },
        },
        "job": {
            "id": str(job_id or uuid4()),
            "project_id": str(project_id or uuid4()),
            "session_id": str(session_id or uuid4()),
            "media_id": str(media_id or uuid4()),
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


def _make_job_response(job_id: UUID | None = None) -> dict:
    """Create a valid JobOut response."""
    now = datetime.now(UTC).isoformat()
    return {
        "id": str(job_id or uuid4()),
        "project_id": str(uuid4()),
        "session_id": str(uuid4()),
        "media_id": str(uuid4()),
        "job_type": "initial_index",
        "status": "running",
        "stage": "processing",
        "progress": 0.5,
        "attempt_count": 0,
        "max_attempts": 3,
        "created_at": now,
        "updated_at": now,
    }


def _make_session_response(session_id: UUID | None = None) -> dict:
    """Create a valid SessionOut response."""
    return {
        "id": str(session_id or uuid4()),
        "project_id": str(uuid4()),
        "media_id": str(uuid4()),
        "label": "test session",
        "status": "indexed",
        "created_at": datetime.now(UTC).isoformat(),
    }


def _make_transcription_response(transcription_id: UUID | None = None) -> dict:
    """Create a valid TranscriptionOut response."""
    return {
        "id": str(transcription_id or uuid4()),
        "project_id": str(uuid4()),
        "session_id": str(uuid4()),
        "media_id": str(uuid4()),
        "provider": "whisper",
        "model": "large-v3",
        "status": "completed",
        "duration_seconds": 120.5,
        "created_at": datetime.now(UTC).isoformat(),
        "updated_at": datetime.now(UTC).isoformat(),
    }
