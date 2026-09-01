"""Celery tasks for clip discovery orchestration.

Implements durable one-window-per-task architecture with cascading scheduling:
1. POST /discover creates DiscoveryRun, creates windows, schedules FIRST window only
2. Each completed window schedules the NEXT pending window OR finalizer
3. Finalizer runs after all windows complete

Recovery:
- Worker startup recovers stale runs and windows
- Stale window timeout: 10 minutes
- Pages Media Indexer with limit <= 500
"""

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from celery import Task
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient, TranscriptSegmentOut
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
from app.services.clip_workflow_service import ClipWorkflowService
from app.services.ninerouter_discovery_provider import (
    NineRouterError as ClipDiscoveryProviderError,
    NineRouterDiscoveryProvider,
)
from app.services.transcript_window_builder import TranscriptWindow

logger = logging.getLogger(__name__)

settings = get_settings()

# Stale window timeout in seconds (10 minutes)
STALE_WINDOW_TIMEOUT_SECONDS = 600

# Page size for Media Indexer pagination
SEGMENT_PAGE_SIZE = 500


def compute_candidate_fingerprint(start_seconds: float, end_seconds: float) -> str:
    """Compute SHA-256 fingerprint for a clip candidate.

    Uses canonical timestamp representation for consistent fingerprinting.
    """
    # Use fixed precision to avoid floating point comparison issues
    canonical = f"{start_seconds:.6f}:{end_seconds:.6f}"
    return hashlib.sha256(canonical.encode()).hexdigest()


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)  # type: ignore[untyped-decorator]
def process_window(self: Task, window_id: str, run_id: str) -> dict[str, Any]:
    """
    Process a single discovery window.

    This is the core unit of work in the durable orchestration.
    Each window is processed in its own task for:
    - Independent retry behavior
    - Parallel execution
    - Recovery from partial failures

    After completion, schedules the next pending window OR finalizer.

    Args:
        window_id: UUID of the window to process
        run_id: UUID of the discovery run

    Returns:
        Dict with processing result
    """
    import asyncio

    return asyncio.run(_process_window(UUID(window_id), UUID(run_id)))


async def _fetch_window_segments_paginated(
    client: MediaIndexerClient,
    transcription_id: UUID,
    window_start: float,
    window_end: float,
) -> list[TranscriptSegmentOut]:
    """
    Fetch segments for a window using pagination.

    Pages Media Indexer with limit <= 500, filters to window segments only.
    Never loads complete transcript into memory.
    """
    all_segments = []
    offset = 0

    while True:
        # Fetch page of segments - returns TranscriptSegmentPage
        page = await client.get_transcript_segments(
            transcription_id=transcription_id,
            offset=offset,
            limit=SEGMENT_PAGE_SIZE,
        )

        # Check if page has items (TranscriptSegmentPage has .items, not truthy check)
        if not page.items:
            break

        # Filter to window time range
        for seg in page.items:
            # Segment overlaps window if it starts before window ends AND ends after window starts
            if seg.start_seconds < window_end and seg.end_seconds > window_start:
                all_segments.append(seg)

        offset += len(page.items)

        # If we got less than page size, we've reached the end
        if len(page.items) < SEGMENT_PAGE_SIZE:
            break

        # Optimization: if last segment is past window, we can stop
        # Check if we've already collected all window segments
        # (last collected segment ends before current page start)
        if (
            page.items
            and page.items[-1].start_seconds >= window_end
            and all_segments
            and all_segments[-1].end_seconds <= page.items[0].start_seconds
        ):
            break

    # Sort by start time
    all_segments.sort(key=lambda s: s.start_seconds)

    return all_segments


async def _process_window(window_id: UUID, run_id: UUID) -> dict[str, Any]:
    """Async implementation of process_window with stale recovery and cascading scheduling."""
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
            logger.info(f"Window {window_id} already completed, scheduling next")
            await _schedule_next_or_finalizer(session, run_id)
            return {"status": "already_completed", "window_id": str(window_id)}

        # Get run
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run_id)
        )
        run = result.scalar_one_or_none()

        if not run:
            logger.error(f"Run {run_id} not found")
            return {"error": f"Run {run_id} not found", "status": "not_found"}

        # Get workflow and source
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

        if not source:
            window.status = "failed"
            window.error_message = "Source not found"
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()
            await _schedule_next_or_finalizer(session, run_id)
            return {"error": "Source not found", "status": "failed"}

        if not source.transcription_id:
            window.status = "failed"
            window.error_message = "Source has no transcription_id"
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()
            await _schedule_next_or_finalizer(session, run_id)
            return {"error": "Source has no transcription_id", "status": "failed"}

        # Mark window as processing (transaction boundary before LLM call)
        window.status = "processing"
        window.processing_started_at = datetime.now(UTC)
        window.updated_at = datetime.now(UTC)
        await session.commit()

        # Fetch segments for this window using pagination
        client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )

        try:
            transcription = await client.get_transcription(source.transcription_id)

            # Fetch segments paginated, filtered to window
            window_segments = await _fetch_window_segments_paginated(
                client=client,
                transcription_id=transcription.id,
                window_start=window.start_seconds,
                window_end=window.end_seconds,
            )

        except Exception as e:
            logger.error(f"Failed to fetch segments for window: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()
            await _schedule_next_or_finalizer(session, run_id)
            return {"error": f"Failed to fetch segments: {e}", "status": "failed"}

        if not window_segments:
            # Empty window, mark as completed
            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.segment_count = 0
            window.updated_at = datetime.now(UTC)
            await _increment_completed_windows(session, run_id)
            await session.commit()
            await _schedule_next_or_finalizer(session, run_id)
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

        # Process with LLM using persisted execution identity
        # Reconstruct provider from DiscoveryRun config (not global defaults)
        # The combo alias is stored in llm_model field
        discovery_provider = NineRouterDiscoveryProvider(
            combo=run.llm_model or settings.nine_router_discovery_combo,
            temperature=0.3,  # TODO: Persist in DiscoveryRun.config_snapshot
            max_candidates_per_window=10,  # TODO: Persist in DiscoveryRun.config_snapshot
        )
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

                    # Use nested transaction (savepoint) to isolate candidate insert
                    # This prevents rollback from erasing prior candidates on duplicate
                    async with session.begin_nested():
                        try:
                            await session.flush()
                            candidates_created += 1
                        except IntegrityError:
                            # Duplicate fingerprint - another concurrent task created it
                            # Savepoint rollback only affects this candidate, not prior ones
                            logger.debug(f"Duplicate candidate fingerprint {fingerprint[:8]}, skipping")
                            continue

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

            logger.info(f"Window {window_id} completed with {candidates_created} candidates")

            # Schedule next window or finalizer
            await _schedule_next_or_finalizer(session, run_id)

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
            await _schedule_next_or_finalizer(session, run_id)
            return {"error": f"Discovery provider error: {e}", "status": "failed"}

        except Exception as e:
            logger.error(f"Window processing failed: {e}", exc_info=True)
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await _increment_failed_windows(session, run_id)
            await session.commit()
            await _schedule_next_or_finalizer(session, run_id)
            return {"error": f"Processing failed: {e}", "status": "failed"}


async def _increment_processed_windows(session: AsyncSession, run_id: UUID) -> None:
    """Atomically increment processed_windows counter.

    processed_windows = completed_windows + failed_windows
    This must be called whenever a window reaches a terminal state.
    """
    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.id == run_id)
        .values(processed_windows=DiscoveryRun.processed_windows + 1)
    )


async def _increment_completed_windows(session: AsyncSession, run_id: UUID) -> None:
    """Atomically increment completed_windows and processed_windows counters."""
    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.id == run_id)
        .values(
            completed_windows=DiscoveryRun.completed_windows + 1,
            processed_windows=DiscoveryRun.processed_windows + 1,
        )
    )


async def _increment_failed_windows(session: AsyncSession, run_id: UUID) -> None:
    """Atomically increment failed_windows and processed_windows counters."""
    await session.execute(
        update(DiscoveryRun)
        .where(DiscoveryRun.id == run_id)
        .values(
            failed_windows=DiscoveryRun.failed_windows + 1,
            processed_windows=DiscoveryRun.processed_windows + 1,
        )
    )


async def _schedule_next_or_finalizer(session: AsyncSession, run_id: UUID) -> None:
    """
    Schedule next pending window OR finalizer.

    Cascading scheduling: each completed window triggers the next.
    """
    # Get next pending window
    result = await session.execute(
        select(DiscoveryWindow)
        .where(DiscoveryWindow.run_id == run_id)
        .where(DiscoveryWindow.status == "pending")
        .order_by(DiscoveryWindow.window_index)
        .limit(1)
    )
    next_window = result.scalar_one_or_none()

    if next_window:
        # Schedule next pending window
        process_window.delay(str(next_window.id), str(run_id))
        logger.info(f"Scheduled next window {next_window.id} for run {run_id}")
    else:
        # No more pending windows - check if all done
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run_id)
        )
        run = result.scalar_one_or_none()

        if run:
            done_count = (run.completed_windows or 0) + (run.failed_windows or 0)
            if done_count >= run.total_windows:
                # All windows done, trigger finalizer
                finalize_discovery.delay(str(run_id))
                logger.info(f"All windows done, scheduled finalizer for run {run_id}")


@celery_app.task(bind=True, max_retries=2)  # type: ignore[untyped-decorator]
def finalize_discovery(self: Task, run_id: str) -> dict[str, Any]:
    """
    Finalize a discovery run after all windows are processed.

    Performs:
    - Deduplication of candidates
    - Updates workflow state to awaiting_selection
    - Marks run as completed

    Args:
        run_id: UUID of the discovery run

    Returns:
        Dict with finalization result
    """
    import asyncio

    return asyncio.run(_finalize_discovery(UUID(run_id)))


async def _finalize_discovery(run_id: UUID) -> dict[str, Any]:
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

        # Reconcile counters from database (authoritative source)
        result = await session.execute(
            select(DiscoveryWindow.status)
            .where(DiscoveryWindow.run_id == run_id)
        )
        window_statuses = [row[0] for row in result.fetchall()]

        actual_completed = sum(1 for s in window_statuses if s == "completed")
        actual_failed = sum(1 for s in window_statuses if s == "failed")
        actual_processed = actual_completed + actual_failed

        # Update counters with reconciled values
        run.completed_windows = actual_completed
        run.failed_windows = actual_failed
        run.processed_windows = actual_processed

        failed_windows = actual_failed
        completed_windows = actual_completed

        if failed_windows > 0 and completed_windows == 0:
            # All windows failed
            run.status = "failed"
            run.error_message = "All windows failed processing"
        elif failed_windows > 0:
            # Some windows failed, some succeeded
            run.status = "completed_with_errors"
            run.error_message = f"{failed_windows} windows failed"
        else:
            # All windows succeeded
            run.status = "completed"

        run.completed_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)

        # Update workflow state using service
        workflow_service = ClipWorkflowService(session)

        if run.status == "failed":
            await workflow_service.transition_status(workflow.id, "failed")
        else:
            await workflow_service.transition_status(workflow.id, "awaiting_selection")

        await session.commit()

        logger.info(f"Finalized run {run_id} with status {run.status}")

        return {
            "status": run.status,
            "run_id": str(run_id),
            "total_candidates": run.total_candidates,
            "failed_windows": failed_windows,
        }


@celery_app.task  # type: ignore[untyped-decorator]
def recover_stale_runs() -> dict[str, Any]:
    """
    Recover stale runs and windows.

    This task should be run on worker startup to recover:
    - Running runs that never completed
    - Pending windows that were never processed
    - Stale processing windows

    Returns:
        Dict with recovery statistics
    """
    import asyncio

    return asyncio.run(_recover_stale_runs())


async def _recover_stale_runs() -> dict[str, Any]:
    """Async implementation of recover_stale_runs."""
    async with async_session_factory() as session:
        stats = {
            "runs_recovered": 0,
            "windows_recovered": 0,
            "windows_dispatched": 0,
        }

        # Find running runs
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.status == "running")
        )
        running_runs = list(result.scalars().all())

        for run in running_runs:
            # Find stale processing windows (stuck for > 10 minutes)
            result = await session.execute(
                select(DiscoveryWindow)
                .where(DiscoveryWindow.run_id == run.id)
                .where(DiscoveryWindow.status == "processing")
            )
            stale_windows = []
            for window in result.scalars().all():
                if window.processing_started_at:
                    elapsed = (datetime.now(UTC) - window.processing_started_at.replace(tzinfo=UTC)).total_seconds()
                    if elapsed >= STALE_WINDOW_TIMEOUT_SECONDS:
                        stale_windows.append(window)
                else:
                    # No timestamp but processing - definitely stale
                    stale_windows.append(window)

            for window in stale_windows:
                window.status = "pending"
                window.processing_started_at = None
                window.attempt_count += 1
                window.updated_at = datetime.now(UTC)
                stats["windows_recovered"] += 1

            # Find pending windows
            result = await session.execute(
                select(DiscoveryWindow)
                .where(DiscoveryWindow.run_id == run.id)
                .where(DiscoveryWindow.status == "pending")
                .order_by(DiscoveryWindow.window_index)
                .limit(1)
            )
            next_pending = result.scalar_one_or_none()

            if next_pending:
                process_window.delay(str(next_pending.id), str(run.id))
                stats["windows_dispatched"] += 1
                stats["runs_recovered"] += 1

        await session.commit()

        logger.info(f"Recovery complete: {stats}")
        return stats
