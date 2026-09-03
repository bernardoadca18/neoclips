"""Service for orchestrating clip rendering (Stage 6).

Manages the workflow of submitting render jobs to Video Composer,
polling for completion, and updating ClipComposition status.
"""

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.video_composer_client import (
    MediaOut,
    RenderJobOut,
    VideoComposerAPIError,
    VideoComposerClient,
    VideoComposerConnectionError,
    VideoComposerError,
    VideoComposerTimeoutError,
)
from app.models.entities import ClipComposition, ClipWorkflow

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
    - Render job submission to Video Composer
    - Status polling and updates
    - Output media registration
    - Workflow state transitions
    """

    def __init__(
        self,
        session: AsyncSession,
        video_composer_client: VideoComposerClient | None = None,
    ) -> None:
        self.session = session
        self.video_composer_client = video_composer_client or VideoComposerClient()

    async def submit_render_job(
        self,
        composition_id: UUID,
        source_media_id: UUID,
    ) -> ClipComposition:
        """
        Submit a render job to Video Composer.

        Args:
            composition_id: UUID of the composition to render
            source_media_id: UUID of the source media to render from

        Returns:
            Updated ClipComposition with render_job_id

        Raises:
            CompositionNotFoundError: If composition doesn't exist
            CompositionNotReadyError: If composition status is not 'ready'
            RenderingError: If job submission fails
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

        try:
            # Submit to Video Composer
            render_job = await self.video_composer_client.submit_render(
                source_media_id=source_media_id,
                start_seconds=composition.source_start_seconds,
                end_seconds=composition.source_end_seconds,
                render_profile=composition.render_profile,
                audio_mode=composition.audio_mode,
                caption_mode=composition.caption_mode,
                idempotency_key=composition.fingerprint,
            )

            # Update composition with render job ID and status
            composition.render_job_id = render_job.id
            composition.status = "rendering"

            # Update workflow status
            await self._transition_workflow_to_rendering(composition.workflow_id)

            await self.session.commit()
            await self.session.refresh(composition)

            logger.info(
                f"Submitted render job {render_job.id} for composition {composition_id}"
            )
            return composition

        except (
            VideoComposerAPIError,
            VideoComposerConnectionError,
            VideoComposerTimeoutError,
        ) as e:
            logger.error(f"Failed to submit render job for composition {composition_id}: {e}")
            composition.status = "failed"
            await self.session.commit()
            raise RenderingError(f"Failed to submit render job: {e}") from e

    async def poll_render_status(self, composition_id: UUID) -> ClipComposition:
        """
        Poll render job status and update composition.

        This is a one-shot poll - Celery tasks handle retry loops.

        Args:
            composition_id: UUID of the composition

        Returns:
            Updated ClipComposition

        Raises:
            CompositionNotFoundError: If composition doesn't exist
            RenderingError: If polling fails
            RenderJobFailedError: If render job failed
        """
        # Get composition
        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.id == composition_id)
        )
        composition = result.scalar_one_or_none()

        if not composition:
            raise CompositionNotFoundError(f"Composition {composition_id} not found")

        if composition.status != "rendering":
            logger.info(
                f"Composition {composition_id} is not rendering (status: {composition.status})"
            )
            return composition

        if not composition.render_job_id:
            raise RenderingError(
                f"Composition {composition_id} has no render_job_id"
            )

        try:
            # Poll Video Composer
            render_job = await self.video_composer_client.get_render_job(
                composition.render_job_id
            )

            # Update based on status
            if render_job.status == "completed":
                composition.status = "completed"
                composition.output_media_id = render_job.output_media_id

                # Transition workflow to packaging
                await self._transition_workflow_to_packaging(composition.workflow_id)

                logger.info(
                    f"Render job {render_job.id} completed for composition {composition_id}"
                )

            elif render_job.status == "failed":
                composition.status = "failed"
                logger.error(
                    f"Render job {render_job.id} failed for composition {composition_id}: "
                    f"{render_job.error}"
                )
                await self.session.commit()
                raise RenderJobFailedError(
                    f"Render job failed: {render_job.error}"
                )

            # For 'pending', 'processing', etc. - no state change
            await self.session.commit()
            await self.session.refresh(composition)
            return composition

        except VideoComposerAPIError as e:
            logger.error(f"Failed to poll render job for composition {composition_id}: {e}")
            raise RenderingError(f"Failed to poll render job: {e}") from e

    async def get_output_media(self, composition_id: UUID) -> MediaOut | None:
        """
        Get output media metadata for a completed composition.

        Args:
            composition_id: UUID of the composition

        Returns:
            MediaOut if composition is completed, None otherwise

        Raises:
            CompositionNotFoundError: If composition doesn't exist
        """
        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.id == composition_id)
        )
        composition = result.scalar_one_or_none()

        if not composition:
            raise CompositionNotFoundError(f"Composition {composition_id} not found")

        if not composition.output_media_id:
            return None

        return await self.video_composer_client.get_media(composition.output_media_id)

    async def _transition_workflow_to_rendering(self, workflow_id: UUID) -> None:
        """Transition workflow to 'rendering' status."""
        result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if workflow and workflow.status == "planning":
            workflow.status = "rendering"
            logger.info(f"Transitioned workflow {workflow_id} to 'rendering'")

    async def _transition_workflow_to_packaging(self, workflow_id: UUID) -> None:
        """Transition workflow to 'packaging' status."""
        result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if workflow and workflow.status == "rendering":
            workflow.status = "packaging"
            logger.info(f"Transitioned workflow {workflow_id} to 'packaging'")


__all__ = [
    "RenderingService",
    "RenderingError",
    "CompositionNotFoundError",
    "CompositionNotReadyError",
    "RenderJobFailedError",
]
