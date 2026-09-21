"""NeoClips Celery tasks for Media Indexer integration.

Design principles:
- One-shot polling: Each task makes a single API call, then either completes or reschedules
- Durable timeout: Uses phase_started_at timestamp, not attempt counter
- Job tracking: Persists media_initial_job_id and transcription_job_id
- State in PostgreSQL: All state transitions persisted, not inferred from task chain
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import select

from app.clients.media_indexer_client import (
    MediaIndexerAPIError,
    MediaIndexerClient,
    MediaIndexerConnectionError,
    MediaIndexerTimeoutError,
)
from app.core.celery_app import celery_app
from app.core.database import async_session_factory
from app.models.entities import ClipSource

logger = logging.getLogger(__name__)

# Import settings for configurable timeouts
from app.core.config import settings


@celery_app.task(name="app.tasks.placeholder")  # type: ignore[untyped-decorator]
def placeholder_task() -> str:
    """Placeholder task for testing Celery setup."""
    return "ok"


def _check_timeout(phase_started_at: datetime | None, timeout_seconds: int) -> bool:
    """Check if phase has exceeded timeout based on elapsed time.

    Uses durable timestamp-based timeout, not attempt counter.
    """
    if phase_started_at is None:
        return False

    elapsed = (datetime.now(UTC) - phase_started_at.replace(tzinfo=UTC)).total_seconds()
    return elapsed > timeout_seconds


@shared_task(  # type: ignore[untyped-decorator]
    name="app.tasks.poll_initial_index",
    bind=True,
    max_retries=3,
)
def poll_initial_index_task(self: Any, source_id: str, attempt: int = 0) -> dict[str, Any]:
    """
    One-shot poll for initial index completion.

    Checks job status once via GET /jobs/{job_id}.
    - If job complete: marks indexed, triggers transcription
    - If job failed: marks source failed
    - If still processing: re-schedules itself with countdown
    - If timeout exceeded: marks source failed

    Args:
        source_id: UUID of ClipSource
        attempt: Legacy attempt counter (unused, kept for compatibility)

    Returns:
        Dict with status
    """
    return asyncio.run(_poll_initial_index_async(UUID(source_id), self, attempt))


async def _poll_initial_index_async(source_id: UUID, task: Any, attempt: int) -> dict[str, Any]:
    """Async implementation of poll_initial_index_task."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ClipSource).where(ClipSource.id == source_id)
        )
        source = result.scalar_one_or_none()

        if not source:
            logger.error("poll_initial_index_not_found", extra={"source_id": str(source_id)})
            return {"status": "failed", "error": "Source not found"}

        if not source.media_initial_job_id:
            logger.error("poll_initial_index_no_job", extra={"source_id": str(source_id)})
            return {"status": "failed", "error": "No media_initial_job_id - cannot poll"}

        # Check durable timeout
        if _check_timeout(source.phase_started_at, settings.media_indexer_initial_index_timeout_seconds):
            logger.error(
                "initial_index_timeout",
                extra={
                    "source_id": str(source_id),
                    "phase_started_at": str(source.phase_started_at),
                },
            )
            source.status = "failed"
            await session.commit()
            return {"status": "failed", "error": "Initial index timeout exceeded"}

        client = MediaIndexerClient()

        try:
            # Poll job status - one-shot call
            job = await client.get_job(source.media_initial_job_id)

            logger.info(
                "initial_index_poll",
                extra={
                    "source_id": str(source_id),
                    "job_id": str(source.media_initial_job_id),
                    "job_status": job.status,
                    "job_stage": job.stage,
                    "job_progress": job.progress,
                },
            )

            if job.status == "completed":
                logger.info(
                    "initial_index_complete",
                    extra={
                        "source_id": str(source_id),
                        "session_id": str(source.media_session_id),
                    },
                )

                # Update status to transcribing
                source.status = "transcribing"
                source.phase_started_at = datetime.now(UTC)
                await session.commit()

                # Trigger transcription - media_session_id must exist at this point
                if not source.media_session_id:
                    logger.error("trigger_transcription_no_session", extra={"source_id": str(source_id)})
                    source.status = "failed"
                    await session.commit()
                    return {"status": "failed", "error": "No media_session_id"}

                transcription_job = await client.trigger_transcription(
                    session_id=source.media_session_id,
                    idempotency_key=f"transcribe-{source_id}",
                )

                # Store transcription ID and job ID
                source.transcription_id = transcription_job.transcription.id
                source.transcription_job_id = transcription_job.job.id
                await session.commit()

                # Start polling transcription with fresh attempt count
                poll_transcription_task.apply_async(
                    args=[str(source_id), 0],
                    countdown=settings.media_indexer_poll_interval_seconds,
                )

                return {
                    "status": "transcribing",
                    "transcription_id": str(transcription_job.transcription.id),
                    "job_id": str(transcription_job.job.id),
                }

            if job.status == "failed":
                error_msg = job.error or "Unknown error"
                logger.error(
                    "initial_index_failed",
                    extra={"source_id": str(source_id), "error": error_msg},
                )
                source.status = "failed"
                await session.commit()
                return {"status": "failed", "error": error_msg}

            # Still processing - re-schedule with countdown
            logger.info(
                "initial_index_poll_continue",
                extra={
                    "source_id": str(source_id),
                    "job_status": job.status,
                    "job_progress": job.progress,
                },
            )

            poll_initial_index_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds,
            )

            return {"status": "polling", "job_status": job.status, "progress": job.progress}

        except MediaIndexerConnectionError as e:
            logger.error(
                "poll_initial_index_connection_error",
                extra={"source_id": str(source_id), "error": str(e)},
            )
            # Re-schedule on connection error
            poll_initial_index_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds * 2,  # Backoff
            )
            return {"status": "retrying", "error": str(e)}

        except MediaIndexerTimeoutError as e:
            logger.error(
                "poll_initial_index_timeout_error",
                extra={"source_id": str(source_id), "error": str(e)},
            )
            # Re-schedule on timeout
            poll_initial_index_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds * 2,
            )
            return {"status": "retrying", "error": str(e)}

        except MediaIndexerAPIError as e:
            logger.error(
                "poll_initial_index_api_error",
                extra={"source_id": str(source_id), "error": str(e), "status_code": e.status_code},
            )
            if e.status_code == 404:
                # Job not found - this is a terminal error
                source.status = "failed"
                await session.commit()
                return {"status": "failed", "error": "Job not found in Media Indexer"}
            # Re-schedule on other API errors
            poll_initial_index_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds * 2,
            )
            return {"status": "retrying", "error": str(e)}


@shared_task(  # type: ignore[untyped-decorator]
    name="app.tasks.poll_transcription",
    bind=True,
    max_retries=3,
)
def poll_transcription_task(self: Any, source_id: str, attempt: int = 0) -> dict[str, Any]:
    """
    One-shot poll for transcription completion.

    Checks job status via GET /jobs/{job_id}.
    - If complete: marks ready_for_discovery
    - If failed: marks source failed
    - If still processing: re-schedules itself
    - If timeout exceeded: marks source failed

    Args:
        source_id: UUID of ClipSource
        attempt: Legacy attempt counter (unused, kept for compatibility)

    Returns:
        Dict with status
    """
    return asyncio.run(_poll_transcription_async(UUID(source_id), self, attempt))


async def _poll_transcription_async(source_id: UUID, task: Any, attempt: int) -> dict[str, Any]:
    """Async implementation of poll_transcription_task."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ClipSource).where(ClipSource.id == source_id)
        )
        source = result.scalar_one_or_none()

        if not source:
            logger.error("poll_transcription_not_found", extra={"source_id": str(source_id)})
            return {"status": "failed", "error": "Source not found"}

        if not source.transcription_job_id:
            logger.error("poll_transcription_no_job", extra={"source_id": str(source_id)})
            return {"status": "failed", "error": "No transcription_job_id - cannot poll"}

        # Check durable timeout
        if _check_timeout(source.phase_started_at, settings.media_indexer_transcription_timeout_seconds):
            logger.error(
                "transcription_timeout",
                extra={
                    "source_id": str(source_id),
                    "phase_started_at": str(source.phase_started_at),
                },
            )
            source.status = "failed"
            await session.commit()
            return {"status": "failed", "error": "Transcription timeout exceeded"}

        client = MediaIndexerClient()

        try:
            # Poll job status - one-shot call
            job = await client.get_job(source.transcription_job_id)

            logger.info(
                "transcription_poll",
                extra={
                    "source_id": str(source_id),
                    "job_id": str(source.transcription_job_id),
                    "job_status": job.status,
                    "job_progress": job.progress,
                },
            )

            if job.status == "completed":
                # Get transcription to confirm - transcription_id must exist at this point
                if not source.transcription_id:
                    logger.error("transcription_complete_no_id", extra={"source_id": str(source_id)})
                    source.status = "failed"
                    await session.commit()
                    return {"status": "failed", "error": "No transcription_id"}

                transcription = await client.get_transcription(source.transcription_id)

                logger.info(
                    "transcription_complete",
                    extra={
                        "source_id": str(source_id),
                        "transcription_id": str(source.transcription_id),
                        "duration_seconds": transcription.duration_seconds,
                    },
                )

                # Terminal Stage 2 state - ready for clip discovery
                source.status = "ready_for_discovery"
                source.phase_started_at = None
                await session.commit()

                return {
                    "status": "ready_for_discovery",
                    "transcription_id": str(source.transcription_id),
                    "duration_seconds": transcription.duration_seconds,
                }

            if job.status == "failed":
                error_msg = job.error or "Unknown error"
                logger.error(
                    "transcription_failed",
                    extra={"source_id": str(source_id), "error": error_msg},
                )
                source.status = "failed"
                await session.commit()
                return {"status": "failed", "error": error_msg}

            # Still processing - re-schedule with countdown
            logger.info(
                "transcription_poll_continue",
                extra={
                    "source_id": str(source_id),
                    "job_status": job.status,
                    "job_progress": job.progress,
                },
            )

            poll_transcription_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds,
            )

            return {"status": "polling", "job_status": job.status, "progress": job.progress}

        except MediaIndexerConnectionError as e:
            logger.error(
                "poll_transcription_connection_error",
                extra={"source_id": str(source_id), "error": str(e)},
            )
            poll_transcription_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds * 2,
            )
            return {"status": "retrying", "error": str(e)}

        except MediaIndexerTimeoutError as e:
            logger.error(
                "poll_transcription_timeout_error",
                extra={"source_id": str(source_id), "error": str(e)},
            )
            poll_transcription_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds * 2,
            )
            return {"status": "retrying", "error": str(e)}

        except MediaIndexerAPIError as e:
            logger.error(
                "poll_transcription_api_error",
                extra={"source_id": str(source_id), "error": str(e), "status_code": e.status_code},
            )
            if e.status_code == 404:
                source.status = "failed"
                await session.commit()
                return {"status": "failed", "error": "Job not found in Media Indexer"}
            poll_transcription_task.apply_async(
                args=[str(source_id), attempt + 1],
                countdown=settings.media_indexer_poll_interval_seconds * 2,
            )
            return {"status": "retrying", "error": str(e)}


@shared_task(  # type: ignore[untyped-decorator]
    name="app.tasks.start_source_pipeline",
    bind=True,
)
def start_source_pipeline_task(self: Any, source_id: str) -> dict[str, Any]:
    """
    Start Media Indexer pipeline for a source.

    This begins polling for initial index completion.
    State is persisted in PostgreSQL, not inferred from task chain.

    Args:
        source_id: UUID of ClipSource

    Returns:
        Dict with status
    """
    return asyncio.run(_start_source_pipeline_async(UUID(source_id)))


async def _start_source_pipeline_async(source_id: UUID) -> dict[str, Any]:
    """Async implementation of start_source_pipeline_task."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(ClipSource).where(ClipSource.id == source_id)
        )
        source = result.scalar_one_or_none()

        if not source:
            logger.error("start_pipeline_not_found", extra={"source_id": str(source_id)})
            return {"status": "failed", "error": "Source not found"}

        if not source.media_initial_job_id:
            logger.error("start_pipeline_no_job", extra={"source_id": str(source_id)})
            return {"status": "failed", "error": "No media_initial_job_id - upload first"}

        # Update status and set phase timestamp for durable timeout
        source.status = "ingesting"
        source.phase_started_at = datetime.now(UTC)
        await session.commit()

        # Start polling
        poll_initial_index_task.apply_async(
            args=[str(source_id), 0],
            countdown=settings.media_indexer_poll_interval_seconds,
        )

        logger.info(
            "source_pipeline_started",
            extra={
                "source_id": str(source_id),
                "job_id": str(source.media_initial_job_id),
            },
        )

        return {
            "status": "started",
            "source_id": str(source_id),
            "job_id": str(source.media_initial_job_id),
        }


@shared_task(  # type: ignore[untyped-decorator]
    name="app.tasks.resume_incomplete_sources",
)
def resume_incomplete_sources() -> int:
    """
    Resume incomplete sources at worker startup.

    This recovers from worker crashes by restarting polling tasks
    for sources stuck in non-terminal states (ingesting, transcribing).

    Returns:
        Number of sources resumed
    """
    return asyncio.run(_resume_incomplete_sources_async())


async def _resume_incomplete_sources_async() -> int:
    """Async implementation of resume_incomplete_sources."""
    resumed = 0

    async with async_session_factory() as session:
        # Find sources in non-terminal states
        result = await session.execute(
            select(ClipSource).where(
                ClipSource.status.in_(["ingesting", "transcribing"])
            )
        )
        sources = result.scalars().all()

        for source in sources:
            if source.status == "ingesting" and source.media_initial_job_id:
                # Resume initial index polling
                poll_initial_index_task.apply_async(
                    args=[str(source.id), 0],
                    countdown=settings.media_indexer_poll_interval_seconds,
                )
                logger.info(
                    "resumed_ingesting",
                    extra={"source_id": str(source.id), "job_id": str(source.media_initial_job_id)},
                )
                resumed += 1

            elif source.status == "transcribing" and source.transcription_job_id:
                # Resume transcription polling
                poll_transcription_task.apply_async(
                    args=[str(source.id), 0],
                    countdown=settings.media_indexer_poll_interval_seconds,
                )
                logger.info(
                    "resumed_transcribing",
                    extra={
                        "source_id": str(source.id),
                        "job_id": str(source.transcription_job_id),
                    },
                )
                resumed += 1

    logger.info("startup_recovery_complete", extra={"resumed_count": resumed})
    return resumed
