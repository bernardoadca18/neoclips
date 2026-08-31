"""Celery tasks for clip discovery orchestration.

Implements durable one-window-per-task architecture:
1. POST /discover creates DiscoveryRun synchronously with idempotency_key
2. process_window task processes a single window (idempotent, recoverable)
3. finalize_discovery task runs after all windows complete
"""

import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient
from app.core.celery_app import celery_app
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.models.entities import (
    ClipCandidate,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    DiscoveryWindow,
)
from app.services.candidate_canonicalizer import CanonicalizationError
from app.services.litellm_http_discovery_provider import (
    ClipDiscoveryProviderError,
    LiteLLMHTTPDiscoveryProvider,
)
from app.services.transcript_window_builder import TranscriptWindow

logger = logging.getLogger(__name__)

settings = get_settings()

# Stale window timeout in seconds (10 minutes)
STALE_WINDOW_TIMEOUT_SECONDS = 600


def compute_candidate_fingerprint(start_seconds: float, end_seconds: float) -> str:
    """Compute SHA-256 fingerprint for a clip candidate.

    Uses canonical timestamp representation for consistent fingerprinting.
    """
    # Use fixed precision to avoid floating point comparison issues
    canonical = f"{start_seconds:.6f}:{end_seconds:.6f}"
    return hashlib.sha256(canonical.encode()).hexdigest()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def process_window(self, window_id: str, run_id: str) -> dict:
    """
    Process a single discovery window.

    This is the core unit of work in the durable orchestration.
    Each window is processed in its own task for:
    - Independent retry behavior
    - Parallel execution
    - Recovery from partial failures

    Args:
        window_id: UUID of the window to process
        run_id: UUID of the discovery run

    Returns:
        Dict with processing result
    """
    import asyncio

    return asyncio.run(_process_window(UUID(window_id), UUID(run_id)))


async def _process_window(window_id: UUID, run_id: UUID) -> dict:
    """Async implementation of process_window with stale recovery."""
    async with async_session_factory() as session:
        # Get window with lock to prevent concurrent processing
        result = await session.execute(
            select(DiscoveryWindow)
            .where(DiscoveryWindow.id == window_id)
            .with_for_update()
        )
        window = result.scalar_one_or_none()

        if not window:
            logger.error(f"Window {window_id} not found")
            return {"error": f"Window {window_id} not found", "status": "not_found"}

        # Stale recovery: check if window is stuck in processing
        if window.status == "processing":
            if window.processing_started_at:
                elapsed = (datetime.now(UTC) - window.processing_started_at.replace(tzinfo=UTC)).total_seconds()
                if elapsed < STALE_WINDOW_TIMEOUT_SECONDS:
                    logger.info(f"Window {window_id} already processing for {elapsed}s, skipping")
                    return {"status": "already_processing", "window_id": str(window_id)}
                # Window is stale, recover it
                logger.warning(f"Recovering stale window {window_id} (processing for {elapsed}s)")
                window.attempt_count += 1
            else:
                # No processing_started_at but status is processing - data corruption
                logger.warning(f"Window {window_id} has no processing_started_at but is processing")
                window.attempt_count += 1

        # Skip already completed windows (idempotency)
        if window.status == "completed":
            logger.info(f"Window {window_id} already completed, skipping")
            return {"status": "already_completed", "window_id": str(window_id)}

        # Get run and workflow
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run_id)
        )
        run = result.scalar_one_or_none()

        if not run:
            logger.error(f"Run {run_id} not found")
            return {"error": f"Run {run_id} not found", "status": "not_found"}

        result = await session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == run.workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            logger.error(f"Workflow for run {run_id} not found")
            return {"error": "Workflow not found", "status": "not_found"}

        result = await session.execute(
            select(ClipSource).where(ClipSource.id == run.source_id)
        )
        source = result.scalar_one_or_none()

        if not source or not source.transcription_id:
            window.status = "failed"
            window.error_message = "Source not found or has no transcription_id"
            window.updated_at = datetime.now(UTC)
            await session.commit()
            return {"error": "Source not found or has no transcription_id", "status": "failed"}

        # Mark window as processing (transaction boundary before LLM call)
        window.status = "processing"
        window.processing_started_at = datetime.now(UTC)
        window.updated_at = datetime.now(UTC)
        await session.commit()

        # Fetch segments for this window
        client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )

        try:
            transcription = await client.get_transcription(source.transcription_id)

            # Fetch segments for this specific window
            segments = await client.get_transcript_segments(
                transcription_id=transcription.id,
                offset=0,
                limit=10000,  # Large limit for window
            )

            # Filter segments to window time range
            window_segments = [
                seg for seg in segments
                if seg.start_seconds < window.end_seconds and seg.end_seconds > window.start_seconds
            ]

        except Exception as e:
            logger.error(f"Failed to fetch segments for window: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()
            return {"error": f"Failed to fetch segments: {e}", "status": "failed"}

        if not window_segments:
            # Empty window, mark as completed
            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.segment_count = 0
            window.updated_at = datetime.now(UTC)
            await _increment_completed_windows(session, run_id)
            await session.commit()
            return {"status": "completed", "window_id": str(window_id), "candidates": 0}

        # Update segment count
        window.segment_count = len(window_segments)

        # Build transcript window
        transcript_window = TranscriptWindow(
            window_index=window.window_index,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            segments=window_segments,
        )

        # Process with LLM
        discovery_provider = LiteLLMHTTPDiscoveryProvider()
        source_duration = transcription.duration_seconds or window_segments[-1].end_seconds
        total_transcript_length = sum(len(seg.text) for seg in window_segments)

        try:
            # Get LLM suggestions
            response, raw_response = await discovery_provider.discover_clips(transcript_window)

            # Store raw response
            window.llm_response_raw = raw_response

            # Canonicalize and create candidates
            from app.services.candidate_canonicalizer import CandidateCanonicalizer
            from app.services.clip_scoring import calculate_clip_score_v1

            canonicalizer = CandidateCanonicalizer(window_segments)
            candidates_created = 0

            for suggestion in response.clips:
                try:
                    start, end, duration = canonicalizer.canonicalize(suggestion)

                    # Compute fingerprint
                    fingerprint = compute_candidate_fingerprint(start, end)

                    # Check for duplicate fingerprint within run
                    existing = await session.execute(
                        select(ClipCandidate).where(
                            ClipCandidate.run_id == run_id,
                            ClipCandidate.candidate_fingerprint == fingerprint,
                        )
                    )
                    if existing.scalar_one_or_none():
                        logger.debug(f"Skipping duplicate candidate with fingerprint {fingerprint[:8]}")
                        continue

                    # Calculate score
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
                        candidate_fingerprint=fingerprint,
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

            # Mark window completed
            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.updated_at = datetime.now(UTC)
            await _increment_completed_windows(session, run_id)
            run.total_candidates = (run.total_candidates or 0) + candidates_created
            await session.commit()

            # Check if all windows complete and trigger finalizer
            await _check_and_finalize(session, run_id)

            return {
                "status": "completed",
                "window_id": str(window_id),
                "candidates": candidates_created,
            }

        except ClipDiscoveryProviderError as e:
            logger.error(f"Discovery provider error: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()

            # Check if we need to finalize despite failure
            await _check_and_finalize(session, run_id)

            return {"error": f"Discovery provider error: {e}", "status": "failed"}

        except Exception as e:
            logger.error(f"Window processing failed: {e}", exc_info=True)
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()

            # Check if we need to finalize despite failure
            await _check_and_finalize(session, run_id)

            return {"error": f"Processing failed: {e}", "status": "failed"}


async def _increment_completed_windows(session: AsyncSession, run_id: UUID) -> None:
    """Atomically increment completed_windows counter."""
    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.id == run_id)
        .values(completed_windows=DiscoveryRun.completed_windows + 1)
    )


async def _increment_failed_windows(session: AsyncSession, run_id: UUID) -> None:
    """Atomically increment failed_windows counter."""
    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.id == run_id)
        .values(failed_windows=DiscoveryRun.failed_windows + 1)
    )


async def _check_and_finalize(session: AsyncSession, run_id: UUID) -> None:
    """Check if all windows are done and trigger finalizer if so."""
    result = await session.execute(
        select(DiscoveryRun).where(DiscoveryRun.id == run_id)
    )
    run = result.scalar_one_or_none()

    if not run:
        return

    # Check if all windows processed
    done_count = (run.completed_windows or 0) + (run.failed_windows or 0)
    if done_count >= run.total_windows:
        # All windows done, trigger finalizer
        finalize_discovery.delay(str(run_id))


@celery_app.task(bind=True, max_retries=2)
def finalize_discovery(self, run_id: str) -> dict:
    """
    Finalize a discovery run after all windows are processed.

    Performs:
    - Deduplication of candidates
    - Updates workflow state
    - Marks run as completed

    Args:
        run_id: UUID of the discovery run

    Returns:
        Dict with finalization result
    """
    import asyncio

    return asyncio.run(_finalize_discovery(UUID(run_id)))


async def _finalize_discovery(run_id: UUID) -> dict:
    """Async implementation of finalize_discovery."""
    async with async_session_factory() as session:
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run_id)
        )
        run = result.scalar_one_or_none()

        if not run:
            return {"error": f"Run {run_id} not found", "status": "not_found"}

        # Check if already finalized (idempotency)
        if run.status in ("completed", "completed_with_errors", "failed"):
            logger.info(f"Run {run_id} already finalized with status {run.status}")
            return {"status": run.status, "run_id": str(run_id)}

        # Get workflow
        result = await session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == run.workflow_id)
        )
        workflow = result.scalar_one_or_none()

        if not workflow:
            run.status = "failed"
            run.error_message = "Workflow not found"
            run.completed_at = datetime.now(UTC)
            await session.commit()
            return {"error": "Workflow not found", "status": "failed"}

        # Deduplicate candidates
        from app.services.candidate_deduplicator import CandidateDeduplicator, CandidateForDedup

        result = await session.execute(
            select(ClipCandidate).where(ClipCandidate.run_id == run_id)
        )
        candidates = list(result.scalars().all())

        if candidates:
            deduplicator = CandidateDeduplicator(iou_threshold=0.5)
            dedup_candidates = [
                CandidateForDedup(
                    id=c.id,
                    start_seconds=c.canonical_start_seconds,
                    end_seconds=c.canonical_end_seconds,
                    score=c.score_v1 or 0.0,
                )
                for c in candidates
            ]

            dedup_results = deduplicator.deduplicate(dedup_candidates)

            # Apply dedup results
            candidate_map = {c.id: c for c in candidates}
            for dedup_result in dedup_results:
                if dedup_result.is_duplicate:
                    candidate = candidate_map.get(dedup_result.candidate_id)
                    if candidate:
                        candidate.is_duplicate = True
                        candidate.duplicate_of_id = dedup_result.duplicate_of_id
                        candidate.updated_at = datetime.now(UTC)

        # Update run status
        failed_windows = run.failed_windows or 0
        if failed_windows > 0 and run.completed_windows == 0:
            run.status = "failed"
            run.error_message = "All windows failed processing"
        elif failed_windows > 0:
            run.status = "completed"
            run.error_message = f"{failed_windows} windows failed"
        else:
            run.status = "completed"

        run.completed_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)

        # Update workflow state
        workflow.current_phase = "awaiting_selection"
        workflow.updated_at = datetime.now(UTC)

        await session.commit()

        logger.info(f"Finalized run {run_id} with status {run.status}")

        return {
            "status": run.status,
            "run_id": str(run_id),
            "total_candidates": run.total_candidates,
            "failed_windows": failed_windows,
        }
