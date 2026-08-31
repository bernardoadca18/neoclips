"""Streaming discovery pipeline for bounded-memory transcript processing.

This module implements the discovery pipeline using a streaming approach
that never loads all transcript segments into memory at once. This is
critical for production workloads with large transcripts (50,000+ segments).

The key insight is that we process windows incrementally:
1. Fetch a page of segments from Media Indexer
2. Identify which windows these segments belong to
3. Accumulate segments only for active windows (bounded by overlap)
4. Process complete windows immediately
5. Discard processed segments to free memory
6. Repeat until all segments processed

This ensures memory usage is O(window_size + page_size), not O(total_segments).
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import (
    MediaIndexerClient,
    TranscriptionOut,
    TranscriptSegmentOut,
)
from app.clients.transcript_segment_stream import (
    TranscriptSegmentStream,
)
from app.models.entities import (
    ClipCandidate,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    DiscoveryWindow,
)
from app.repositories.discovery_repository import (
    ClipCandidateRepository,
    DiscoveryRunRepository,
    DiscoveryWindowRepository,
)
from app.services.candidate_canonicalizer import CandidateCanonicalizer, CanonicalizationError
from app.services.candidate_deduplicator import CandidateDeduplicator, CandidateForDedup
from app.services.clip_scoring import calculate_clip_score_v1
from app.services.litellm_http_discovery_provider import (
    ClipDiscoveryProviderError,
    LiteLLMHTTPDiscoveryProvider,
)
from app.services.transcript_window_builder import TranscriptWindow, WindowConfig

logger = logging.getLogger(__name__)


class StreamingDiscoveryError(Exception):
    """Base error for streaming discovery."""

    pass


class SourceNotReadyError(StreamingDiscoveryError):
    """Raised when source is not ready for discovery."""

    pass


class TranscriptionNotFoundError(StreamingDiscoveryError):
    """Raised when transcription is not found."""

    pass


@dataclass
class WindowBuffer:
    """Buffer for accumulating segments for a discovery window.

    This holds segments that belong to a specific window until the window
    is complete (all overlapping segments have been fetched), then the
    window can be processed and the buffer cleared.
    """

    window: DiscoveryWindow
    segments: list[TranscriptSegmentOut] = field(default_factory=list)
    is_complete: bool = False

    def add_segment(self, segment: TranscriptSegmentOut) -> None:
        """Add a segment to this window buffer."""
        self.segments.append(segment)

    def mark_complete(self) -> None:
        """Mark this window as ready for processing."""
        self.is_complete = True

    def clear(self) -> None:
        """Clear the buffer after processing."""
        self.segments = []
        self.is_complete = False


@dataclass
class StreamingDiscoveryResult:
    """Result of a streaming discovery run."""

    run_id: UUID
    status: str
    total_windows: int
    processed_windows: int
    total_candidates: int
    failed_windows: int
    error_message: str | None = None


class StreamingDiscoveryService:
    """Streaming discovery pipeline with bounded memory usage.

    This service implements the discovery pipeline using streaming
    transcript processing. Memory usage is bounded by:
    - page_size: Number of segments fetched per API call
    - concurrent_windows: Number of windows being buffered at once

    The service processes windows as they become complete, discarding
    segments immediately after processing to free memory.

    Usage:
        service = StreamingDiscoveryService(session, client)
        result = await service.run_discovery(workflow)

    The pipeline:
    1. Create DiscoveryRun with durable identity fields
    2. Pre-compute window boundaries (without segments)
    3. Stream transcript pages from Media Indexer
    4. Route segments to active window buffers
    5. Process windows as they become complete
    6. Deduplicate and finalize
    """

    def __init__(
        self,
        session: AsyncSession,
        discovery_provider: LiteLLMHTTPDiscoveryProvider | None = None,
        window_config: WindowConfig | None = None,
        iou_threshold: float = 0.5,
        page_size: int = 500,
    ) -> None:
        """Initialize the streaming discovery service.

        Args:
            session: SQLAlchemy async session
            discovery_provider: LLM provider for clip discovery
            window_config: Window building configuration
            iou_threshold: IoU threshold for deduplication
            page_size: Number of segments per page fetch
        """
        self.session = session
        self.run_repository = DiscoveryRunRepository(session)
        self.window_repository = DiscoveryWindowRepository(session)
        self.candidate_repository = ClipCandidateRepository(session)
        self.discovery_provider = discovery_provider or LiteLLMHTTPDiscoveryProvider()
        self.window_config = window_config or WindowConfig()
        self.deduplicator = CandidateDeduplicator(iou_threshold)
        self.page_size = page_size

    async def run_discovery(
        self,
        workflow: ClipWorkflow,
        source: ClipSource,
        transcription: TranscriptionOut,
        client: MediaIndexerClient,
    ) -> StreamingDiscoveryResult:
        """Run the complete discovery pipeline with streaming.

        This is the main entry point for streaming discovery. It orchestrates
        the entire pipeline while maintaining bounded memory usage.

        Args:
            workflow: The workflow to run discovery for
            source: The clip source
            transcription: The transcription from Media Indexer
            client: Media Indexer client for fetching segments

        Returns:
            StreamingDiscoveryResult with run details

        Raises:
            StreamingDiscoveryError: If discovery fails
        """
        logger.info(
            "streaming_discovery_started",
            extra={
                "workflow_id": str(workflow.id),
                "source_id": str(source.id),
                "transcription_id": str(transcription.id),
            },
        )

        # Step 1: Create discovery run with durable identity
        run = await self._create_run(workflow, source, transcription)

        try:
            # Step 2: Pre-compute window boundaries
            # We need to know window boundaries before streaming
            # Fetch just the first and last segment to determine duration
            stream = TranscriptSegmentStream(
                client=client,
                transcription_id=transcription.id,
                page_size=self.page_size,
            )

            # Pre-compute windows based on transcription duration
            source_duration = transcription.duration_seconds or 0.0
            windows = self._compute_window_boundaries(source_duration)

            # Create DB windows (without segments yet)
            db_windows = await self._create_windows(run, windows)

            # Step 3: Stream segments and process windows incrementally
            total_transcript_length = 0
            processed_count = 0

            # Window buffers - keyed by window_index
            window_buffers: dict[int, WindowBuffer] = {}

            async for page in stream:
                # Accumulate transcript length for scoring
                total_transcript_length += sum(len(seg.text) for seg in page.items)

                # Route segments to window buffers
                for segment in page.items:
                    self._route_segment_to_windows(
                        segment=segment,
                        db_windows=db_windows,
                        window_buffers=window_buffers,
                    )

                # Process complete windows
                for window_idx, buffer in list(window_buffers.items()):
                    if buffer.is_complete:
                        await self._process_window_buffer(
                            buffer=buffer,
                            source_duration=source_duration,
                            total_transcript_length=total_transcript_length,
                        )
                        processed_count += 1
                        # Remove processed buffer to free memory
                        del window_buffers[window_idx]

                # Mark windows as complete when we've passed their end time
                self._check_window_completion(
                    window_buffers=window_buffers,
                    current_segments=page.items,
                    db_windows=db_windows,
                )

            # Process any remaining windows
            for buffer in window_buffers.values():
                if len(buffer.segments) > 0:
                    buffer.mark_complete()
                    await self._process_window_buffer(
                        buffer=buffer,
                        source_duration=source_duration,
                        total_transcript_length=total_transcript_length,
                    )
                    processed_count += 1

            # Step 4: Deduplicate candidates
            duplicate_count = await self._deduplicate_candidates(run)

            # Step 5: Finalize run
            await self._finalize_run(run)

            logger.info(
                "streaming_discovery_completed",
                extra={
                    "run_id": str(run.id),
                    "total_windows": run.total_windows,
                    "processed_windows": run.processed_windows,
                    "total_candidates": run.total_candidates,
                    "duplicates": duplicate_count,
                },
            )

            return StreamingDiscoveryResult(
                run_id=run.id,
                status=run.status,
                total_windows=run.total_windows,
                processed_windows=run.processed_windows,
                total_candidates=run.total_candidates,
                failed_windows=run.total_windows - run.processed_windows,
                error_message=run.error_message,
            )

        except Exception as e:
            logger.error(
                "streaming_discovery_failed",
                extra={
                    "run_id": str(run.id),
                    "error": str(e),
                },
            )
            run.status = "failed"
            run.error_message = str(e)
            run.updated_at = datetime.now(UTC)
            await self.session.flush()

            raise StreamingDiscoveryError(f"Discovery failed: {e}") from e

    async def _create_run(
        self,
        workflow: ClipWorkflow,
        source: ClipSource,
        transcription: TranscriptionOut,
    ) -> DiscoveryRun:
        """Create a discovery run with durable identity fields."""
        run = DiscoveryRun(
            id=uuid4(),
            workflow_id=workflow.id,
            source_id=source.id,
            transcription_id=transcription.id,
            strategy_id=self._compute_strategy_id(),
            prompt_id=self._compute_prompt_id(),
            config_snapshot=self._serialize_config(),
            status="pending",
            profile="transcript_only",
            llm_model=self.discovery_provider.model,
            llm_provider=self.discovery_provider.model.split("/")[0] if "/" in self.discovery_provider.model else "unknown",
            total_windows=0,
            processed_windows=0,
            total_candidates=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.session.add(run)
        await self.session.flush()
        return run

    def _compute_strategy_id(self) -> str:
        """Compute a hash of the discovery strategy config."""
        import hashlib
        import json

        config = {
            "window_duration": self.window_config.window_duration_seconds,
            "overlap": self.window_config.overlap_seconds,
            "iou_threshold": self.deduplicator.iou_threshold,
        }
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def _compute_prompt_id(self) -> str:
        """Compute a hash of the LLM prompt."""
        import hashlib

        prompt = self.discovery_provider._build_system_prompt()
        return hashlib.sha256(prompt.encode()).hexdigest()[:16]

    def _serialize_config(self) -> str:
        """Serialize the discovery config for auditing."""
        import json

        return json.dumps({
            "window_config": {
                "window_duration_seconds": self.window_config.window_duration_seconds,
                "overlap_seconds": self.window_config.overlap_seconds,
                "min_segment_count": self.window_config.min_segment_count,
            },
            "llm_model": self.discovery_provider.model,
            "iou_threshold": self.deduplicator.iou_threshold,
        })

    def _compute_window_boundaries(self, source_duration: float) -> list[tuple[int, float, float]]:
        """Compute window boundaries without needing all segments.

        Returns list of (window_index, start_seconds, end_seconds).
        """
        windows = []
        window_index = 0
        current_start = 0.0
        step = self.window_config.window_duration_seconds - self.window_config.overlap_seconds

        while current_start < source_duration:
            window_end = min(
                current_start + self.window_config.window_duration_seconds,
                source_duration,
            )
            windows.append((window_index, current_start, window_end))
            window_index += 1
            current_start += step

        return windows

    async def _create_windows(
        self,
        run: DiscoveryRun,
        boundaries: list[tuple[int, float, float]],
    ) -> list[DiscoveryWindow]:
        """Create DiscoveryWindow entities from pre-computed boundaries."""
        db_windows = []
        for window_index, start_seconds, end_seconds in boundaries:
            db_window = DiscoveryWindow(
                id=uuid4(),
                run_id=run.id,
                window_index=window_index,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                segment_count=0,  # Will be updated during processing
                status="pending",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db_windows.append(db_window)
            self.session.add(db_window)

        run.total_windows = len(db_windows)
        await self.session.flush()
        return db_windows

    def _route_segment_to_windows(
        self,
        segment: TranscriptSegmentOut,
        db_windows: list[DiscoveryWindow],
        window_buffers: dict[int, WindowBuffer],
    ) -> None:
        """Route a segment to all windows it overlaps with."""
        for db_window in db_windows:
            # Check if segment overlaps with this window
            if segment.start_seconds < db_window.end_seconds and segment.end_seconds > db_window.start_seconds:
                # Get or create buffer for this window
                if db_window.window_index not in window_buffers:
                    window_buffers[db_window.window_index] = WindowBuffer(window=db_window)

                window_buffers[db_window.window_index].add_segment(segment)

    def _check_window_completion(
        self,
        window_buffers: dict[int, WindowBuffer],
        current_segments: list[TranscriptSegmentOut],
        db_windows: list[DiscoveryWindow],
    ) -> None:
        """Check if any windows can be marked as complete.

        A window is complete when we've fetched all segments that
        could possibly overlap with it (i.e., we've moved past its end time).
        """
        if not current_segments:
            return

        # Get the maximum end time from current page
        max_segment_end = max(seg.end_seconds for seg in current_segments)

        for db_window in db_windows:
            # If we've passed the window's end, mark it complete
            if max_segment_end > db_window.end_seconds + self.window_config.overlap_seconds:
                if db_window.window_index in window_buffers:
                    window_buffers[db_window.window_index].mark_complete()

    async def _process_window_buffer(
        self,
        buffer: WindowBuffer,
        source_duration: float,
        total_transcript_length: int,
    ) -> list[ClipCandidate]:
        """Process a window buffer and create candidates."""
        window = buffer.window
        segments = buffer.segments

        if not segments:
            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.updated_at = datetime.now(UTC)
            await self.session.flush()
            return []

        window.status = "processing"
        window.segment_count = len(segments)
        window.updated_at = datetime.now(UTC)
        await self.session.flush()

        # Build TranscriptWindow
        transcript_window = TranscriptWindow(
            window_index=window.window_index,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            segments=segments,
        )

        try:
            # Get LLM suggestions
            response, raw_response = await self.discovery_provider.discover_clips(transcript_window)

            # Store raw response
            window.llm_response_raw = raw_response

            # Canonicalize suggestions
            canonicalizer = CandidateCanonicalizer(segments)
            candidates = []

            for suggestion in response.clips:
                try:
                    start, end, duration = canonicalizer.canonicalize(suggestion)

                    # Calculate score
                    clip_text = " ".join(
                        seg.text for seg in segments
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
                    candidates.append(candidate)

                except CanonicalizationError as e:
                    logger.warning(f"Canonicalization failed: {e}")
                    continue

            # Store parsed response
            import json
            window.llm_response_parsed = json.dumps({
                "clips": [
                    {
                        "start_segment_id": str(s.start_segment_id),
                        "end_segment_id": str(s.end_segment_id),
                        "title": s.title,
                        "summary": s.summary,
                        "hook_type": s.hook_type,
                        "hook_description": s.hook_description,
                    }
                    for s in response.clips
                ]
            })

            # Add candidates to session
            for candidate in candidates:
                self.session.add(candidate)

            window.status = "completed"
            window.processed_at = datetime.now(UTC)
            window.updated_at = datetime.now(UTC)

            await self.session.flush()
            return candidates

        except ClipDiscoveryProviderError as e:
            logger.error(f"Discovery provider error: {e}")
            window.status = "failed"
            window.error_message = str(e)
            window.updated_at = datetime.now(UTC)
            await self.session.flush()
            return []

    async def _deduplicate_candidates(self, run: DiscoveryRun) -> int:
        """Deduplicate candidates within a run."""
        candidates = await self.candidate_repository.get_by_run_id(run.id)

        dedup_candidates = [
            CandidateForDedup(
                id=c.id,
                start_seconds=c.canonical_start_seconds,
                end_seconds=c.canonical_end_seconds,
                score=c.score_v1 or 0.0,
            )
            for c in candidates
        ]

        results = self.deduplicator.deduplicate(dedup_candidates)

        duplicate_count = 0
        for result in results:
            if result.is_duplicate:
                candidate = next(c for c in candidates if c.id == result.candidate_id)
                candidate.is_duplicate = True
                candidate.duplicate_of_id = result.duplicate_of_id
                candidate.updated_at = datetime.now(UTC)
                duplicate_count += 1

        await self.session.flush()
        return duplicate_count

    async def _finalize_run(self, run: DiscoveryRun) -> None:
        """Finalize the discovery run."""
        candidates = await self.candidate_repository.get_by_run_id(run.id)
        run.total_candidates = len(candidates)

        windows = await self.window_repository.get_by_run_id(run.id)
        run.processed_windows = sum(1 for w in windows if w.status == "completed")

        failed_windows = sum(1 for w in windows if w.status == "failed")
        if failed_windows > 0 and run.processed_windows == 0:
            run.status = "failed"
            run.error_message = "All windows failed processing"
        elif failed_windows > 0:
            run.status = "completed"
            run.error_message = f"{failed_windows} windows failed"
        else:
            run.status = "completed"

        run.completed_at = datetime.now(UTC)
        run.updated_at = datetime.now(UTC)

        await self.session.flush()


__all__ = [
    "StreamingDiscoveryService",
    "StreamingDiscoveryResult",
    "StreamingDiscoveryError",
    "SourceNotReadyError",
    "TranscriptionNotFoundError",
    "WindowBuffer",
]
