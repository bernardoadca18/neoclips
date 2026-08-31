"""Celery tasks for clip discovery orchestration."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from app.clients.media_indexer_client import MediaIndexerClient
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.entities import ClipWorkflow, DiscoveryRun, DiscoveryWindow
from app.services.discovery_service import DiscoveryService
from app.services.transcript_window_builder import WindowConfig

logger = logging.getLogger(__name__)

settings = get_settings()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_discovery(self, workflow_id: str) -> dict:
    """
    Run clip discovery for a workflow.

    This is the main entry point for Stage 3 discovery.
    It orchestrates the entire discovery pipeline.

    Args:
        workflow_id: UUID of the workflow to run discovery for

    Returns:
        Dict with run_id and status
    """
    import asyncio

    return asyncio.run(_run_discovery(UUID(workflow_id)))


async def _run_discovery(workflow_id: UUID) -> dict:
    """Async implementation of run_discovery."""
    async with async_session_factory() as session:
        # Get workflow
        from sqlalchemy import select
        result = await session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            return {"error": f"Workflow {workflow_id} not found"}

        # Get source
        from app.models.entities import ClipSource
        result = await session.execute(
            select(ClipSource).where(ClipSource.id == workflow.source_id)
        )
        source = result.scalar_one_or_none()

        if not source:
            return {"error": f"Source for workflow {workflow_id} not found"}

        # Check source is ready
        if source.status != "ready_for_discovery":
            return {"error": f"Source status is {source.status}, must be ready_for_discovery"}

        # Get transcript from Media Indexer
        client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )

        if not source.transcription_id:
            return {"error": "Source has no transcription_id"}

        try:
            transcription = await client.get_transcription(source.transcription_id)
            segments_response = await client.get_transcript_segments(source.transcription_id)
            segments = segments_response.items
        except Exception as e:
            logger.error(f"Failed to get transcript: {e}")
            return {"error": f"Failed to get transcript: {e}"}

        if not segments:
            return {"error": "No transcript segments found"}

        # Create discovery service
        discovery_service = DiscoveryService(
            session=session,
            window_config=WindowConfig(
                window_duration_seconds=300.0,
                overlap_seconds=60.0,
            ),
        )

        # Create run
        run = await discovery_service.create_run(workflow)

        # Build windows
        db_windows = await discovery_service.build_windows(run, segments)

        # Process each window
        source_duration = transcription.duration_seconds or segments[-1].end_seconds
        total_transcript_length = sum(len(seg.text) for seg in segments)

        for db_window in db_windows:
            # Get segments for this window
            window_segments = [
                seg for seg in segments
                if seg.start_seconds < db_window.end_seconds
                and seg.end_seconds > db_window.start_seconds
            ]

            await discovery_service.process_window(
                window=db_window,
                segments=window_segments,
                source_duration=source_duration,
                total_transcript_length=total_transcript_length,
            )

        # Deduplicate candidates
        await discovery_service.deduplicate_candidates(run)

        # Finalize run
        await discovery_service.finalize_run(run)

        # Update workflow status
        workflow.current_phase = "discovering"
        workflow.updated_at = datetime.now(UTC)
        await session.commit()

        return {
            "run_id": str(run.id),
            "status": run.status,
            "total_windows": run.total_windows,
            "total_candidates": run.total_candidates,
        }


@celery_app.task(bind=True)
def process_discovery_window(self, run_id: str, window_id: str) -> dict:
    """
    Process a single discovery window.

    This can be used for parallel window processing.

    Args:
        run_id: UUID of the discovery run
        window_id: UUID of the window to process

    Returns:
        Dict with processing result
    """
    import asyncio

    return asyncio.run(_process_discovery_window(UUID(run_id), UUID(window_id)))


async def _process_discovery_window(run_id: UUID, window_id: UUID) -> dict:
    """Async implementation of process_discovery_window."""
    async with async_session_factory() as session:
        from sqlalchemy import select

        # Get window
        result = await session.execute(
            select(DiscoveryWindow).where(DiscoveryWindow.id == window_id)
        )
        window = result.scalar_one_or_none()

        if not window:
            return {"error": f"Window {window_id} not found"}

        # Get run
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run_id)
        )
        run = result.scalar_one_or_none()

        if not run:
            return {"error": f"Run {run_id} not found"}

        # TODO: Implement single window processing
        return {"window_id": str(window_id), "status": "processed"}
