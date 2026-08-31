"""Celery tasks for clip discovery orchestration."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from app.clients.media_indexer_client import MediaIndexerClient
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.entities import ClipCandidate, ClipWorkflow, DiscoveryRun, DiscoveryWindow
from app.services.streaming_discovery import StreamingDiscoveryService
from app.services.transcript_window_builder import WindowConfig

logger = logging.getLogger(__name__)

settings = get_settings()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def run_discovery(self, workflow_id: str) -> dict:
    """
    Run clip discovery for a workflow.

    This is the main entry point for Stage 3 discovery.
    It orchestrates the entire discovery pipeline using streaming
    transcript processing for bounded memory usage.

    Args:
        workflow_id: UUID of the workflow to run discovery for

    Returns:
        Dict with run_id and status
    """
    import asyncio

    return asyncio.run(_run_discovery(UUID(workflow_id)))


async def _run_discovery(workflow_id: UUID) -> dict:
    """Async implementation of run_discovery using streaming."""
    async with async_session_factory() as session:
        from sqlalchemy import select

        # Get workflow
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

        # Get transcript metadata from Media Indexer
        client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )

        if not source.transcription_id:
            return {"error": "Source has no transcription_id"}

        try:
            transcription = await client.get_transcription(source.transcription_id)
        except Exception as e:
            logger.error(f"Failed to get transcription: {e}")
            return {"error": f"Failed to get transcription: {e}"}

        # Create streaming discovery service
        discovery_service = StreamingDiscoveryService(
            session=session,
            window_config=WindowConfig(
                window_duration_seconds=300.0,
                overlap_seconds=60.0,
            ),
            page_size=500,  # Bounded page size for memory safety
        )

        try:
            # Run streaming discovery - never loads all segments into memory
            result = await discovery_service.run_discovery(
                workflow=workflow,
                source=source,
                transcription=transcription,
                client=client,
            )

            # Update workflow status
            workflow.current_phase = "discovering"
            workflow.updated_at = datetime.now(UTC)
            await session.commit()

            return {
                "run_id": str(result.run_id),
                "status": result.status,
                "total_windows": result.total_windows,
                "processed_windows": result.processed_windows,
                "total_candidates": result.total_candidates,
                "failed_windows": result.failed_windows,
            }

        except Exception as e:
            logger.error(f"Discovery failed: {e}")
            await session.rollback()
            return {"error": f"Discovery failed: {e}"}


@celery_app.task(bind=True, max_retries=2, default_retry_delay=30)
def process_discovery_window(self, run_id: str, window_id: str) -> dict:
    """
    Process a single discovery window.

    This can be used for parallel window processing when the main
    run_discovery task has already created windows.

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

        from app.models.entities import ClipSource

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

        # Get workflow and source
        result = await session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == run.workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            return {"error": f"Workflow for run {run_id} not found"}

        result = await session.execute(
            select(ClipSource).where(ClipSource.id == run.source_id)
        )
        source = result.scalar_one_or_none()

        if not source or not source.transcription_id:
            return {"error": "Source not found or has no transcription_id"}

        # Get transcription from Media Indexer
        client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )

        try:
            transcription = await client.get_transcription(source.transcription_id)

            # Fetch segments for this specific window using streaming
            from app.clients.transcript_segment_stream import TranscriptSegmentStream

            stream = TranscriptSegmentStream(
                client=client,
                transcription_id=transcription.id,
                page_size=500,
            )

            # Fetch only segments for this window
            window_segments = await stream.fetch_all_for_window(
                window_start_seconds=window.start_seconds,
                window_end_seconds=window.end_seconds,
            )

        except Exception as e:
            logger.error(f"Failed to fetch segments for window: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await session.commit()
            return {"error": f"Failed to fetch segments: {e}"}

        if not window_segments:
            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.updated_at = datetime.now(UTC)
            await session.commit()
            return {"window_id": str(window_id), "status": "completed", "candidates": 0}

        from uuid import uuid4

        from app.services.candidate_canonicalizer import (
            CandidateCanonicalizer,
            CanonicalizationError,
        )
        from app.services.clip_scoring import calculate_clip_score_v1
        from app.services.litellm_http_discovery_provider import (
            ClipDiscoveryProviderError,
            LiteLLMHTTPDiscoveryProvider,
        )
        from app.services.transcript_window_builder import TranscriptWindow

        discovery_provider = LiteLLMHTTPDiscoveryProvider()
        source_duration = transcription.duration_seconds or window_segments[-1].end_seconds
        total_transcript_length = sum(len(seg.text) for seg in window_segments)

        transcript_window = TranscriptWindow(
            window_index=window.window_index,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            segments=window_segments,
        )

        window.status = "processing"
        window.segment_count = len(window_segments)
        window.updated_at = datetime.now(UTC)
        await session.flush()

        try:
            # Get LLM suggestions
            response, raw_response = await discovery_provider.discover_clips(transcript_window)

            window.llm_response_raw = raw_response

            # Canonicalize and create candidates
            canonicalizer = CandidateCanonicalizer(window_segments)
            candidates_created = 0

            for suggestion in response.clips:
                try:
                    start, end, duration = canonicalizer.canonicalize(suggestion)

                    clip_text = " ".join(
                        seg.text for seg in window_segments
                        if seg.start_seconds < end and seg.end_seconds > start
                    )
                    score, components = calculate_clip_score_v1(
                        clip_start_seconds=start,
                        clip_end_seconds=end,
                        clip_transcript_length=len(clip_text),
                        hook_type=suggestion.hook_type,
                        source_duration_seconds=source_duration,
                        total_transcript_length=total_transcript_length,
                    )

                    candidate = ClipCandidate(
                        id=uuid4(),
                        run_id=window.run_id,
                        window_id=window.id,
                        llm_suggested_start_segment_id=suggestion.start_segment_id,
                        llm_suggested_end_segment_id=suggestion.end_segment_id,
                        canonical_start_seconds=start,
                        canonical_end_seconds=end,
                        duration_seconds=duration,
                        title=suggestion.title,
                        summary=suggestion.summary,
                        hook_type=suggestion.hook_type,
                        hook_description=suggestion.hook_description,
                        hook_strength=suggestion.hook_strength,
                        standalone_clarity=suggestion.standalone_clarity,
                        narrative_completeness=suggestion.narrative_completeness,
                        emotional_intensity=suggestion.emotional_intensity,
                        topic_relevance=suggestion.topic_relevance,
                        score_v1=score,
                        score_v1_components=components,
                        is_duplicate=False,
                        selected=False,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    session.add(candidate)
                    candidates_created += 1

                except CanonicalizationError as e:
                    logger.warning(f"Canonicalization failed: {e}")
                    continue

            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.updated_at = datetime.now(UTC)
            await session.commit()

            return {
                "window_id": str(window_id),
                "status": "completed",
                "candidates": candidates_created,
            }

        except ClipDiscoveryProviderError as e:
            logger.error(f"Discovery provider error: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await session.commit()
            return {"error": f"Discovery provider error: {e}"}

        except Exception as e:
            logger.error(f"Window processing failed: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await session.commit()
            return {"error": f"Processing failed: {e}"}
