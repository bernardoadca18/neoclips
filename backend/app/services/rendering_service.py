"""Service for orchestrating clip rendering (Stage 6).

Manages the workflow of submitting render jobs to Video Composer,
polling for completion, and updating ClipComposition status.

For M4-A milestone: Uses LocalClipRenderer for direct FFmpeg-based rendering
instead of Video Composer HTTP API.
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient, MediaIndexerAPIError
from app.models.entities import ClipComposition, ClipSource, ClipWorkflow
from app.services.local_clip_renderer import (
    LocalClipRenderer,
    RenderFailedError,
    RenderOutput,
    get_local_clip_renderer,
)

logger = logging.getLogger(__name__)


class RenderingError(Exception):
    """Base error for rendering service."""

    pass


class CompositionNotFoundError(RenderingError):
    """Raised when composition is not found."""

    pass


class CompositionNotReadyError(RenderingError):
    """Raised when composition is not ready for rendering."""

    pass


class RenderJobFailedError(RenderingError):
    """Raised when render job fails."""

    pass


class RenderingService:
    """
    Service for orchestrating clip rendering.

    Handles:
    - Local FFmpeg-based clip rendering (M4-A milestone)
    - Source media path resolution from Media Indexer
    - Output media registration
    - Workflow state transitions

    Note: For M4-A, rendering is done locally via FFmpeg instead of
    delegating to Video Composer HTTP API. This bypasses the timeline-based
    ProductionTimeline contract that Video Composer requires.
    """

    def __init__(
        self,
        session: AsyncSession,
        media_indexer_client: MediaIndexerClient | None = None,
        local_renderer: LocalClipRenderer | None = None,
    ) -> None:
        self.session = session
        self.media_indexer_client = media_indexer_client or MediaIndexerClient()
        self.local_renderer = local_renderer or get_local_clip_renderer()

    async def submit_render_job(
        self,
        composition_id: UUID,
        source_media_id: UUID,
    ) -> ClipComposition:
        """
        Render a clip locally using FFmpeg.

        For M4-A milestone, rendering is done synchronously via LocalClipRenderer
        instead of submitting to Video Composer HTTP API.

        Args:
            composition_id: UUID of the composition to render
            source_media_id: UUID of the source media to render from

        Returns:
            Updated ClipComposition with output_media_id

        Raises:
            CompositionNotFoundError: If composition doesn't exist
            CompositionNotReadyError: If composition status is not 'ready'
            RenderingError: If rendering fails
        """
        # Get composition
        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.id == composition_id)
        )
        composition = result.scalar_one_or_none()

        if not composition:
            raise CompositionNotFoundError(f"Composition {composition_id} not found")

        if composition.status != "ready":
            raise CompositionNotReadyError(
                f"Composition {composition_id} is not ready (status: {composition.status}). "
                "Composition must be in 'ready' status before rendering."
            )

        # Get workflow to find source
        workflow_result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == composition.workflow_id)
        )
        workflow = workflow_result.scalar_one_or_none()
        if not workflow:
            raise RenderingError(f"Workflow {composition.workflow_id} not found")

        # Get source to find media_session_id
        source_result = await self.session.execute(
            select(ClipSource).where(ClipSource.id == workflow.source_id)
        )
        source = source_result.scalar_one_or_none()
        if not source:
            raise RenderingError(f"Source for workflow {workflow.id} not found")

        try:
            # Get source media path from Media Indexer
            source_path = await self._get_source_media_path(source.media_session_id, source_media_id)

            # Update status to rendering
            composition.status = "rendering"
            await self._transition_workflow_to_rendering(composition.workflow_id)
            await self.session.commit()

            # Render clip locally using FFmpeg
            render_output = await self.local_renderer.render_clip(
                composition_id=composition_id,
                source_path=source_path,
                source_start_seconds=composition.source_start_seconds,
                source_end_seconds=composition.source_end_seconds,
            )

            # Update composition with output details
            composition.status = "completed"
            composition.output_media_id = composition_id  # Use composition_id as output_media_id

            # Update workflow status
            await self._transition_workflow_to_completed(composition.workflow_id)

            await self.session.commit()
            await self.session.refresh(composition)

            logger.info(
                "clip_render_completed",
                extra={
                    "composition_id": str(composition_id),
                    "output_path": render_output.output_path,
                    "sha256": render_output.sha256,
                    "duration_seconds": render_output.duration_seconds,
                },
            )
            return composition

        except (MediaIndexerAPIError, RenderFailedError) as e:
            logger.error(f"Failed to render clip for composition {composition_id}: {e}")
            composition.status = "failed"
            await self.session.commit()
            raise RenderingError(f"Failed to render clip: {e}") from e

    async def _get_source_media_path(
        self, media_session_id: UUID | None, source_media_id: UUID
    ) -> str:
        """
        Get the local file path for source media from Media Indexer.

        Args:
            media_session_id: UUID of the media session in Media Indexer
            source_media_id: UUID of the source media

        Returns:
            Local file path to the source media

        Raises:
            RenderingError: If media path cannot be resolved
        """
        if not media_session_id:
            raise RenderingError("media_session_id is required to resolve source media path")

        try:
            # Get session from Media Indexer to find media storage_uri
            session = await self.media_indexer_client.get_session(media_session_id)

            if not session.media:
                raise RenderingError(f"Media not found for session {media_session_id}")

            # Media Indexer returns storage_uri which is a local path or URL
            # For local development, this should be a file path
            storage_uri = session.media.storage_uri

            # If it's a file:// URI, convert to path
            if storage_uri.startswith("file://"):
                return storage_uri[7:]

            # If it's already a path, return as-is
            if os.path.exists(storage_uri):
                return storage_uri

            # Otherwise, assume it's a path relative to a media root
            # This may need adjustment based on Media Indexer configuration
            media_root = os.getenv("MEDIA_INDEXER_ROOT", "/tmp/media-indexer/media")
            full_path = os.path.join(media_root, storage_uri)
            if os.path.exists(full_path):
                return full_path

            raise RenderingError(f"Source media file not found: {storage_uri}")

        except MediaIndexerAPIError as e:
            raise RenderingError(f"Failed to get source media from Media Indexer: {e}") from e

    async def _transition_workflow_to_completed(self, workflow_id: UUID) -> None:
        """Transition workflow to completed status."""
        result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()
        if workflow:
            workflow.status = "completed"
            workflow.completed_at = datetime.now(UTC)

    async def poll_render_status(self, composition_id: UUID) -> ClipComposition:
        """
        Poll render job status and update composition.

        For M4-A milestone with local rendering, this is a no-op since
        rendering is synchronous and completes in submit_render_job().

        This method is kept for API compatibility but simply returns
        the current composition status.

        Args:
            composition_id: UUID of the composition

        Returns:
            Current ClipComposition state

        Raises:
            CompositionNotFoundError: If composition doesn't exist
        """
        # Get composition
        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.id == composition_id)
        )
        composition = result.scalar_one_or_none()

        if not composition:
            raise CompositionNotFoundError(f"Composition {composition_id} not found")

        # With local rendering, status is already final
        # This method exists for API compatibility with polling-based architecture
        logger.info(
            "poll_render_status_checked",
            extra={
                "composition_id": str(composition_id),
                "status": composition.status,
            },
        )
        return composition

    async def get_output_media(self, composition_id: UUID) -> RenderOutput | None:
        """
        Get output media metadata for a completed composition.

        For M4-A milestone, returns metadata from the locally rendered file.

        Args:
            composition_id: UUID of the composition

        Returns:
            RenderOutput if composition is completed, None otherwise

        Raises:
            CompositionNotFoundError: If composition doesn't exist
        """
        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.id == composition_id)
        )
        composition = result.scalar_one_or_none()

        if not composition:
            raise CompositionNotFoundError(f"Composition {composition_id} not found")

        if composition.status != "completed":
            return None

        # Get output file from local renderer
        output_path = Path(self.local_renderer.output_root) / f"{composition_id}.mp4"
        if not output_path.exists():
            logger.warning(
                "output_file_not_found",
                extra={"composition_id": str(composition_id), "path": str(output_path)},
            )
            return None

        # Compute SHA256 and get metadata
        import hashlib

        sha256_hash = hashlib.sha256()
        with open(output_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256_hash.update(chunk)
        sha256 = sha256_hash.hexdigest()

        stat = output_path.stat()
        byte_size = stat.st_size

        # Get duration/dimensions using ffprobe
        info = await self.local_renderer.get_media_info(str(output_path))
        format_info = info.get("format", {})
        streams = info.get("streams", [])
        video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)

        duration = float(format_info.get("duration", 0))
        width = video_stream.get("width", 1080) if video_stream else 1080
        height = video_stream.get("height", 1920) if video_stream else 1920

        return RenderOutput(
            output_path=str(output_path),
            sha256=sha256,
            duration_seconds=duration,
            width=width,
            height=height,
            byte_size=byte_size,
            content_type="video/mp4",
        )

    async def _transition_workflow_to_rendering(self, workflow_id: UUID) -> None:
        """Transition workflow to 'rendering' status."""
        result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if workflow and workflow.status == "planning":
            workflow.status = "rendering"
            logger.info(f"Transitioned workflow {workflow_id} to 'rendering'")


def get_rendering_service(session: AsyncSession) -> RenderingService:
    """Dependency injection for RenderingService with MediaIndexerClient."""
    return RenderingService(
        session=session,
        media_indexer_client=MediaIndexerClient(),
        local_renderer=get_local_clip_renderer(),
    )


__all__ = [
    "RenderingService",
    "RenderingError",
    "CompositionNotFoundError",
    "CompositionNotReadyError",
    "RenderJobFailedError",
]
