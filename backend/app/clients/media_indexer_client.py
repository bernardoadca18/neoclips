"""Media Indexer HTTP client for NeoClips.

This client communicates with the Media Indexer API using the correct contract:
- No /api/v1 prefix (root-level routes)
- Ingest via POST /projects/{project_id}/sessions with multipart form
- Job polling via GET /jobs/{job_id}
- Transcription segments via GET /transcriptions/{id}/segments
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# Response models matching Media Indexer API


class MediaOut(BaseModel):
    """Media asset from Media Indexer."""

    id: UUID
    storage_uri: str
    original_filename: str
    content_type: str | None = None
    byte_size: int
    sha256: str
    duration_seconds: float | None = None
    format_name: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None

    model_config = {"extra": "ignore"}


class SessionOut(BaseModel):
    """Session from Media Indexer."""

    id: UUID
    project_id: UUID
    media_id: UUID
    label: str
    status: str
    notes_filename: str | None = None
    raw_notes: str | None = None
    created_at: datetime
    media: MediaOut | None = None

    model_config = {"extra": "ignore"}


class JobOut(BaseModel):
    """ProcessingJob from Media Indexer."""

    id: UUID
    project_id: UUID
    session_id: UUID
    media_id: UUID
    transcription_id: UUID | None = None
    job_type: str
    status: str
    stage: str
    progress: float
    heartbeat_at: datetime | None = None
    attempt_count: int
    max_attempts: int
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "ignore"}


class SessionIngestOut(BaseModel):
    """Response from POST /projects/{project_id}/sessions (ingest)."""

    session: SessionOut
    job: JobOut

    model_config = {"extra": "ignore"}


class ProjectOut(BaseModel):
    """Project from Media Indexer."""

    id: UUID
    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "ignore"}


class TranscriptionOut(BaseModel):
    """Transcription from Media Indexer."""

    id: UUID
    project_id: UUID
    session_id: UUID
    media_id: UUID
    provider: str
    model: str
    language_requested: str | None = None
    language_detected: str | None = None
    status: str
    duration_seconds: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "ignore"}


class TranscriptionJobOut(BaseModel):
    """Response from POST /sessions/{session_id}/transcriptions."""

    transcription: TranscriptionOut
    job: JobOut
    created: bool

    model_config = {"extra": "ignore"}


class TranscriptSegmentOut(BaseModel):
    """Single transcript segment with timing."""

    id: UUID
    transcription_id: UUID
    sequence: int
    start_seconds: float
    end_seconds: float
    text: str
    avg_logprob: float | None = None
    no_speech_prob: float | None = None
    compression_ratio: float | None = None
    word_timestamps: list[dict[str, Any]] | None = None

    model_config = {"extra": "ignore"}


class TranscriptSegmentPage(BaseModel):
    """Paginated transcript segments."""

    items: list[TranscriptSegmentOut]
    total: int
    offset: int
    limit: int

    model_config = {"extra": "ignore"}


# Exceptions


class MediaIndexerError(Exception):
    """Base exception for Media Indexer errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class MediaIndexerConnectionError(MediaIndexerError):
    """Raised when connection to Media Indexer fails."""

    pass


class MediaIndexerTimeoutError(MediaIndexerError):
    """Raised when request to Media Indexer times out."""

    pass


class MediaIndexerAPIError(MediaIndexerError):
    """Raised when Media Indexer returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_body: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class MediaIndexerClient:
    """HTTP client for Media Indexer API.

    Design principles:
    - One HTTP call per method - no internal retries
    - No blocking wait loops - polling handled by Celery tasks
    - Caller handles retries via Celery retry mechanism
    - All state transitions persisted to PostgreSQL

    API Contract (no /api/v1 prefix):
    - GET /projects - list projects
    - POST /projects - create project
    - POST /projects/{project_id}/sessions - ingest video (multipart: label, video, notes)
    - GET /sessions/{session_id} - get session
    - GET /jobs/{job_id} - get job status
    - POST /sessions/{session_id}/transcriptions - trigger transcription
    - GET /transcriptions/{transcription_id} - get transcription
    - GET /transcriptions/{transcription_id}/segments - get transcript segments
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        project_name: str | None = None,
    ) -> None:
        _settings = get_settings()
        self.base_url = (base_url or _settings.media_indexer_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or _settings.media_indexer_timeout_seconds
        self.project_name = project_name or _settings.media_indexer_project_name
        self._project_id: UUID | None = None

    def _get_client(self, timeout: int | None = None) -> httpx.AsyncClient:
        """Get async HTTP client configured with timeout."""
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout or self.timeout_seconds),
            follow_redirects=True,
        )

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Make a single HTTP request without retry logic.

        Retries are handled at Celery task level, not client level.
        Connection/timeout errors are raised for caller to handle.
        """
        try:
            async with self._get_client() as client:
                response = await client.request(method, f"{self.base_url}{path}", **kwargs)
                return response
        except httpx.ConnectError as e:
            raise MediaIndexerConnectionError(f"Connection refused: {e}") from e
        except httpx.TimeoutException as e:
            raise MediaIndexerTimeoutError(f"Request timed out: {e}") from e

    async def _ensure_project(self) -> UUID:
        """Ensure project exists, creating if necessary."""
        if self._project_id:
            return self._project_id

        # List projects to find ours
        response = await self._request("GET", "/projects")

        if response.status_code == 200:
            projects = response.json()
            for project in projects:
                if project.get("name") == self.project_name:
                    self._project_id = UUID(project["id"])
                    logger.info(
                        "media_indexer_project_resolved",
                        extra={"project_id": str(self._project_id), "name": self.project_name},
                    )
                    return self._project_id

        # Create new project
        response = await self._request(
            "POST",
            "/projects",
            json={
                "name": self.project_name,
                "description": "Managed sources for NeoClips clip discovery pipeline",
            },
        )

        if response.status_code not in (200, 201):
            raise MediaIndexerAPIError(
                f"Failed to create project: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        data = response.json()
        self._project_id = UUID(data["id"])
        logger.info(
            "media_indexer_project_created",
            extra={"project_id": str(self._project_id), "name": self.project_name},
        )
        return self._project_id

    async def ingest_video(
        self,
        video_file: Any,  # file-like object with read() and name
        label: str,
        notes_content: str = "",
        idempotency_key: str | None = None,
    ) -> SessionIngestOut:
        """Ingest video to Media Indexer using multipart form upload.

        Uses POST /projects/{project_id}/sessions with multipart form:
        - label: string (required)
        - video: file (required)
        - notes: file (optional, can be empty)

        Returns SessionIngestOut with session and job for tracking.

        This method uses streaming upload - the video_file should be a file-like
        object that supports read(), not bytes in memory.
        """
        project_id = await self._ensure_project()

        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        # Build multipart form data
        # httpx supports file-like objects directly for streaming
        files = {
            "video": (getattr(video_file, "name", "video.mp4"), video_file, "video/mp4"),
            "notes": ("notes.txt", notes_content.encode(), "text/plain"),
        }
        data = {"label": label}

        response = await self._request(
            "POST",
            f"/projects/{project_id}/sessions",
            files=files,
            data=data,
            headers=headers,
        )

        if response.status_code not in (200, 201, 202):
            raise MediaIndexerAPIError(
                f"Failed to ingest video: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        result = response.json()
        ingest_out = SessionIngestOut(**result)

        logger.info(
            "media_indexer_ingest_complete",
            extra={
                "session_id": str(ingest_out.session.id),
                "job_id": str(ingest_out.job.id),
                "media_id": str(ingest_out.session.media_id),
                "label": label,
            },
        )

        return ingest_out

    async def get_session(self, session_id: UUID) -> SessionOut:
        """Get session metadata by ID - one-shot call for polling."""
        response = await self._request("GET", f"/sessions/{session_id}")

        if response.status_code == 404:
            raise MediaIndexerAPIError(f"Session not found: {session_id}", status_code=404)

        if response.status_code != 200:
            raise MediaIndexerAPIError(
                f"Failed to get session: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return SessionOut(**response.json())

    async def get_job(self, job_id: UUID) -> JobOut:
        """Get job status by ID - one-shot call for polling."""
        response = await self._request("GET", f"/jobs/{job_id}")

        if response.status_code == 404:
            raise MediaIndexerAPIError(f"Job not found: {job_id}", status_code=404)

        if response.status_code != 200:
            raise MediaIndexerAPIError(
                f"Failed to get job: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return JobOut(**response.json())

    async def trigger_transcription(
        self,
        session_id: UUID,
        model: str | None = None,
        language: str | None = None,
        idempotency_key: str | None = None,
    ) -> TranscriptionJobOut:
        """Trigger transcription for a session.

        Uses POST /sessions/{session_id}/transcriptions.
        Returns TranscriptionJobOut with transcription and job for tracking.
        """
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload: dict[str, Any] = {}
        if model:
            payload["model"] = model
        if language:
            payload["language"] = language

        response = await self._request(
            "POST",
            f"/sessions/{session_id}/transcriptions",
            json=payload,
            headers=headers,
        )

        if response.status_code == 404:
            raise MediaIndexerAPIError(f"Session not found: {session_id}", status_code=404)

        if response.status_code == 409:
            raise MediaIndexerAPIError(
                "Session not ready or transcription attempts exhausted",
                status_code=409,
                response_body=response.text,
            )

        if response.status_code not in (200, 201, 202):
            raise MediaIndexerAPIError(
                f"Failed to trigger transcription: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        result = response.json()
        return TranscriptionJobOut(**result)

    async def get_transcription(self, transcription_id: UUID) -> TranscriptionOut:
        """Get transcription by ID - one-shot call for polling."""
        response = await self._request("GET", f"/transcriptions/{transcription_id}")

        if response.status_code == 404:
            raise MediaIndexerAPIError(
                f"Transcription not found: {transcription_id}",
                status_code=404,
            )

        if response.status_code != 200:
            raise MediaIndexerAPIError(
                f"Failed to get transcription: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return TranscriptionOut(**response.json())

    async def get_transcript_segments(
        self,
        transcription_id: UUID,
        offset: int = 0,
        limit: int = 500,
    ) -> TranscriptSegmentPage:
        """Get transcript segments with pagination.

        Uses GET /transcriptions/{transcription_id}/segments.
        This is the preferred way to access transcript content.

        Note: This returns a SINGLE page. For complete transcript access,
        use get_all_transcript_segments() which handles pagination automatically.
        """
        response = await self._request(
            "GET",
            f"/transcriptions/{transcription_id}/segments",
            params={"offset": offset, "limit": limit},
        )

        if response.status_code == 404:
            raise MediaIndexerAPIError(
                f"Transcription not found: {transcription_id}",
                status_code=404,
            )

        if response.status_code != 200:
            raise MediaIndexerAPIError(
                f"Failed to get transcript segments: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return TranscriptSegmentPage(**response.json())

    async def get_all_transcript_segments(
        self,
        transcription_id: UUID,
        page_size: int = 500,
    ) -> list[TranscriptSegmentOut]:
        """Get ALL transcript segments, handling pagination automatically.

        This method fetches all pages until the complete transcript is retrieved.
        Use this when you need the entire transcript, not just one page.

        Args:
            transcription_id: UUID of the transcription
            page_size: Number of segments per page (default 500)

        Returns:
            List of all TranscriptSegmentOut objects

        Raises:
            MediaIndexerAPIError: If transcription not found or API error
            MediaIndexerConnectionError: If connection fails
            MediaIndexerTimeoutError: If request times out
        """
        all_segments: list[TranscriptSegmentOut] = []
        offset = 0

        while True:
            page = await self.get_transcript_segments(
                transcription_id=transcription_id,
                offset=offset,
                limit=page_size,
            )

            all_segments.extend(page.items)

            # Check if we've fetched all segments
            if offset + len(page.items) >= page.total:
                break

            offset += len(page.items)

            # Safety: prevent infinite loops
            if len(page.items) == 0:
                logger.warning(
                    "empty_transcript_page",
                    extra={
                        "transcription_id": str(transcription_id),
                        "offset": offset,
                        "total": page.total,
                    },
                )
                break

        logger.info(
            "all_transcript_segments_fetched",
            extra={
                "transcription_id": str(transcription_id),
                "total_segments": len(all_segments),
            },
        )

        return all_segments

    async def list_transcriptions_for_session(self, session_id: UUID) -> list[TranscriptionOut]:
        """List transcriptions for a session."""
        response = await self._request("GET", f"/sessions/{session_id}/transcriptions")

        if response.status_code == 404:
            raise MediaIndexerAPIError(f"Session not found: {session_id}", status_code=404)

        if response.status_code != 200:
            raise MediaIndexerAPIError(
                f"Failed to list transcriptions: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return [TranscriptionOut(**t) for t in response.json()]

    async def health_check(self) -> bool:
        """Check if Media Indexer is healthy."""
        try:
            async with self._get_client(timeout=5) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False


def get_media_indexer_client() -> MediaIndexerClient:
    """Dependency injection for MediaIndexerClient."""
    return MediaIndexerClient()
