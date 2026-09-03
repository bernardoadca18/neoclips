"""Video Composer HTTP client for NeoClips.

This client communicates with the Video Composer API for rendering clips:
- Submit render jobs via POST /renders
- Poll job status via GET /renders/{render_id}
- Retrieve output media via GET /media/{media_id}
"""

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)


# Response models matching Video Composer API


class RenderJobOut(BaseModel):
    """Render job from Video Composer."""

    id: UUID
    source_media_id: UUID
    status: str
    progress: float
    output_media_id: UUID | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"extra": "ignore"}


class RenderJobCreate(BaseModel):
    """Request body for creating a render job."""

    source_media_id: UUID
    start_seconds: float
    end_seconds: float
    render_profile: str = "vertical_short_v1"
    audio_mode: str = "original"
    caption_mode: str = "none"
    idempotency_key: str | None = None

    model_config = {"extra": "forbid"}


class MediaOut(BaseModel):
    """Output media from Video Composer."""

    id: UUID
    storage_uri: str
    original_filename: str
    content_type: str | None = None
    byte_size: int
    sha256: str
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None

    model_config = {"extra": "ignore"}


# Exceptions


class VideoComposerError(Exception):
    """Base exception for Video Composer errors."""

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class VideoComposerConnectionError(VideoComposerError):
    """Raised when connection to Video Composer fails."""

    pass


class VideoComposerTimeoutError(VideoComposerError):
    """Raised when request to Video Composer times out."""

    pass


class VideoComposerAPIError(VideoComposerError):
    """Raised when Video Composer returns an error response."""

    def __init__(
        self,
        message: str,
        status_code: int,
        response_body: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(message)


class VideoComposerClient:
    """HTTP client for Video Composer API.

    Design principles (same as MediaIndexerClient):
    - One HTTP call per method - no internal retries
    - No blocking wait loops - polling handled by Celery tasks
    - Caller handles retries via Celery retry mechanism
    - All state transitions persisted to PostgreSQL

    API Contract:
    - POST /renders - submit render job
    - GET /renders/{render_id} - get render job status
    - GET /media/{media_id} - get output media metadata
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        _settings = get_settings()
        self.base_url = (base_url or _settings.video_composer_base_url).rstrip("/")
        self.timeout_seconds = timeout_seconds or _settings.video_composer_timeout_seconds

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
            raise VideoComposerConnectionError(f"Connection refused: {e}") from e
        except httpx.TimeoutException as e:
            raise VideoComposerTimeoutError(f"Request timed out: {e}") from e

    async def submit_render(
        self,
        source_media_id: UUID,
        start_seconds: float,
        end_seconds: float,
        render_profile: str = "vertical_short_v1",
        audio_mode: str = "original",
        caption_mode: str = "none",
        idempotency_key: str | None = None,
    ) -> RenderJobOut:
        """Submit a render job to Video Composer.

        Uses POST /renders with JSON body.

        Args:
            source_media_id: UUID of the source media to render from
            start_seconds: Start time in seconds
            end_seconds: End time in seconds
            render_profile: Render profile to use (default: vertical_short_v1)
            audio_mode: Audio handling mode (default: original)
            caption_mode: Caption handling mode (default: none)
            idempotency_key: Optional idempotency key for deduplication

        Returns:
            RenderJobOut with job details

        Raises:
            VideoComposerAPIError: If API returns error
            VideoComposerConnectionError: If connection fails
            VideoComposerTimeoutError: If request times out
        """
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key

        payload = {
            "source_media_id": str(source_media_id),
            "start_seconds": start_seconds,
            "end_seconds": end_seconds,
            "render_profile": render_profile,
            "audio_mode": audio_mode,
            "caption_mode": caption_mode,
        }

        response = await self._request(
            "POST",
            "/renders",
            json=payload,
            headers=headers,
        )

        if response.status_code not in (200, 201, 202):
            raise VideoComposerAPIError(
                f"Failed to submit render job: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        result = response.json()
        job = RenderJobOut(**result)

        logger.info(
            "video_composer_render_submitted",
            extra={
                "render_id": str(job.id),
                "source_media_id": str(source_media_id),
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
                "render_profile": render_profile,
            },
        )

        return job

    async def get_render_job(self, render_id: UUID) -> RenderJobOut:
        """Get render job status by ID - one-shot call for polling.

        Args:
            render_id: UUID of the render job

        Returns:
            RenderJobOut with current job status

        Raises:
            VideoComposerAPIError: If job not found or API error
            VideoComposerConnectionError: If connection fails
            VideoComposerTimeoutError: If request times out
        """
        response = await self._request("GET", f"/renders/{render_id}")

        if response.status_code == 404:
            raise VideoComposerAPIError(f"Render job not found: {render_id}", status_code=404)

        if response.status_code != 200:
            raise VideoComposerAPIError(
                f"Failed to get render job: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return RenderJobOut(**response.json())

    async def get_media(self, media_id: UUID) -> MediaOut:
        """Get output media metadata by ID.

        Args:
            media_id: UUID of the media

        Returns:
            MediaOut with media metadata

        Raises:
            VideoComposerAPIError: If media not found or API error
            VideoComposerConnectionError: If connection fails
            VideoComposerTimeoutError: If request times out
        """
        response = await self._request("GET", f"/media/{media_id}")

        if response.status_code == 404:
            raise VideoComposerAPIError(f"Media not found: {media_id}", status_code=404)

        if response.status_code != 200:
            raise VideoComposerAPIError(
                f"Failed to get media: {response.status_code}",
                status_code=response.status_code,
                response_body=response.text,
            )

        return MediaOut(**response.json())

    async def health_check(self) -> bool:
        """Check if Video Composer is healthy."""
        try:
            async with self._get_client(timeout=5) as client:
                response = await client.get(f"{self.base_url}/health")
                return response.status_code == 200
        except Exception:
            return False


def get_video_composer_client() -> VideoComposerClient:
    """Dependency injection for VideoComposerClient."""
    return VideoComposerClient()
