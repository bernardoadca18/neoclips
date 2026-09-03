"""Celery tasks for clip rendering (Stage 6).

Design principles:
- One-shot execution: Each task performs a single poll
- State in PostgreSQL: All state transitions persisted
- Error handling: Failures are recorded in composition record
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from celery import shared_task

from app.core.celery_app import celery_app
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.submit_render_job")  # type: ignore[untyped-decorator]
def submit_render_job(composition_id: str, source_media_id: str) -> dict[str, Any]:
    """
    Submit a render job to Video Composer.

    Args:
        composition_id: UUID of the ClipComposition
        source_media_id: UUID of the source media to render from

    Returns:
        Dict with status and composition_id
    """
    return asyncio.run(
        _submit_render_job_async(UUID(composition_id), UUID(source_media_id))
    )


async def _submit_render_job_async(
    composition_id: UUID,
    source_media_id: UUID,
) -> dict[str, Any]:
    """Async implementation of submit_render_job task."""
    from app.services.rendering_service import (
        CompositionNotFoundError,
        CompositionNotReadyError,
        RenderingError,
        RenderingService,
    )

    async with async_session_factory() as session:
        service = RenderingService(session)

        try:
            composition = await service.submit_render_job(
                composition_id=composition_id,
                source_media_id=source_media_id,
            )
            logger.info(
                "render_job_submitted",
                extra={
                    "composition_id": str(composition_id),
                    "render_job_id": str(composition.render_job_id),
                },
            )
            return {
                "status": "success",
                "composition_id": str(composition_id),
                "render_job_id": str(composition.render_job_id),
            }

        except CompositionNotFoundError as e:
            logger.error(
                "render_job_composition_not_found",
                extra={"composition_id": str(composition_id)},
            )
            return {"status": "failed", "error": str(e)}

        except CompositionNotReadyError as e:
            logger.warning(
                "render_job_composition_not_ready",
                extra={"composition_id": str(composition_id), "error": str(e)},
            )
            return {"status": "skipped", "reason": "not_ready"}

        except RenderingError as e:
            logger.error(
                "render_job_submission_failed",
                extra={"composition_id": str(composition_id), "error": str(e)},
            )
            return {"status": "failed", "error": str(e)}


@celery_app.task(name="app.tasks.poll_render_status")  # type: ignore[untyped-decorator]
def poll_render_status(composition_id: str) -> dict[str, Any]:
    """
    Poll render job status (one-shot poll).

    This task should be scheduled periodically while composition is rendering.
    Celery beat or external scheduler handles the retry loop.

    Args:
        composition_id: UUID of the ClipComposition

    Returns:
        Dict with status and composition status
    """
    return asyncio.run(_poll_render_status_async(UUID(composition_id)))


async def _poll_render_status_async(composition_id: UUID) -> dict[str, Any]:
    """Async implementation of poll_render_status task."""
    from app.services.rendering_service import (
        CompositionNotFoundError,
        RenderJobFailedError,
        RenderingError,
        RenderingService,
    )

    async with async_session_factory() as session:
        service = RenderingService(session)

        try:
            composition = await service.poll_render_status(composition_id)

            logger.info(
                "render_status_polled",
                extra={
                    "composition_id": str(composition_id),
                    "status": composition.status,
                },
            )

            return {
                "status": "success",
                "composition_id": str(composition_id),
                "composition_status": composition.status,
            }

        except CompositionNotFoundError as e:
            logger.error(
                "render_poll_composition_not_found",
                extra={"composition_id": str(composition_id)},
            )
            return {"status": "failed", "error": str(e)}

        except RenderJobFailedError as e:
            logger.error(
                "render_job_failed",
                extra={"composition_id": str(composition_id), "error": str(e)},
            )
            return {"status": "failed", "error": str(e), "composition_status": "failed"}

        except RenderingError as e:
            logger.error(
                "render_poll_failed",
                extra={"composition_id": str(composition_id), "error": str(e)},
            )
            return {"status": "failed", "error": str(e)}


__all__ = ["submit_render_job", "poll_render_status"]
