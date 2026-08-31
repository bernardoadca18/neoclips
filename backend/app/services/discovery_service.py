"""Discovery orchestration service.

Coordinates the clip discovery pipeline:
1. Create DiscoveryRun and DiscoveryWindows
2. Process each window through ClipDiscoveryProvider
3. Canonicalize candidates with CandidateCanonicalizer
4. Score candidates with ClipScorer
5. Deduplicate candidates with CandidateDeduplicator
"""

import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import TranscriptSegmentOut
from app.models.entities import ClipCandidate, ClipWorkflow, DiscoveryRun, DiscoveryWindow
from app.repositories.discovery_repository import (
    ClipCandidateRepository,
    DiscoveryRunRepository,
    DiscoveryWindowRepository,
)
from app.services.candidate_canonicalizer import CandidateCanonicalizer, CanonicalizationError
from app.services.candidate_deduplicator import CandidateDeduplicator, CandidateForDedup
from app.services.clip_discovery_provider import ClipDiscoveryProvider, ClipDiscoveryProviderError
from app.services.clip_scoring import calculate_clip_score_v1
from app.services.transcript_window_builder import TranscriptWindowBuilder, WindowConfig

logger = logging.getLogger(__name__)


class DiscoveryServiceError(Exception):
    """Base error for discovery service."""

    pass


class SourceNotReadyError(DiscoveryServiceError):
    """Raised when source is not ready for discovery."""

    pass


class DiscoveryService:
    """
    Orchestrates the clip discovery pipeline.

    The service coordinates:
    - Window building from transcripts
    - LLM-based clip discovery
    - Timestamp canonicalization
    - Deterministic scoring
    - Deduplication
    """

    def __init__(
        self,
        session: AsyncSession,
        discovery_provider: ClipDiscoveryProvider | None = None,
        window_config: WindowConfig | None = None,
        iou_threshold: float = 0.5,
    ) -> None:
        self.session = session
        self.run_repository = DiscoveryRunRepository(session)
        self.window_repository = DiscoveryWindowRepository(session)
        self.candidate_repository = ClipCandidateRepository(session)
        self.discovery_provider = discovery_provider or ClipDiscoveryProvider()
        self.window_builder = TranscriptWindowBuilder(window_config)
        self.deduplicator = CandidateDeduplicator(iou_threshold)

    async def create_run(
        self,
        workflow: ClipWorkflow,
        profile: str = "transcript_only",
    ) -> DiscoveryRun:
        """
        Create a new discovery run for a workflow.

        Args:
            workflow: The workflow to run discovery for
            profile: Discovery profile (transcript_only, transcript_plus_visual, full_multimodal)

        Returns:
            Created DiscoveryRun
        """
        run = DiscoveryRun(
            id=uuid4(),
            workflow_id=workflow.id,
            status="pending",
            profile=profile,
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

    async def build_windows(
        self,
        run: DiscoveryRun,
        segments: list[TranscriptSegmentOut],
    ) -> list[DiscoveryWindow]:
        """
        Build discovery windows from transcript segments.

        Args:
            run: The discovery run
            segments: Transcript segments from Media Indexer

        Returns:
            List of created DiscoveryWindow entities
        """
        windows = self.window_builder.build(segments)

        db_windows = []
        for window in windows:
            db_window = DiscoveryWindow(
                id=uuid4(),
                run_id=run.id,
                window_index=window.window_index,
                start_seconds=window.start_seconds,
                end_seconds=window.end_seconds,
                segment_count=window.segment_count,
                status="pending",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            db_windows.append(db_window)
            self.session.add(db_window)

        run.total_windows = len(db_windows)
        await self.session.flush()

        return db_windows

    async def process_window(
        self,
        window: DiscoveryWindow,
        segments: list[TranscriptSegmentOut],
        source_duration: float,
        total_transcript_length: int,
    ) -> list[ClipCandidate]:
        """
        Process a single discovery window.

        Args:
            window: The window to process
            segments: Transcript segments for this window
            source_duration: Total source duration
            total_transcript_length: Total transcript character count

        Returns:
            List of created ClipCandidate entities
        """
        window.status = "processing"
        window.updated_at = datetime.now(UTC)
        await self.session.flush()

        # Build TranscriptWindow from DB window
        from app.services.transcript_window_builder import TranscriptWindow
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
                        score_v1=score,
                        score_v1_components=components,
                        is_duplicate=False,
                        selected=False,
                        created_at=datetime.now(UTC),
                        updated_at=datetime.now(UTC),
                    )
                    candidates.append(candidate)

                except CanonicalizationError as e:
                    logger.warning(f"Canonicalization failed for suggestion: {e}")
                    continue

            # Store parsed response
            window.llm_response_parsed = json.dumps({  # type: ignore[assignment]
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

    async def deduplicate_candidates(self, run: DiscoveryRun) -> int:
        """
        Deduplicate candidates within a run.

        Args:
            run: The discovery run

        Returns:
            Number of duplicates marked
        """
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

    async def finalize_run(self, run: DiscoveryRun) -> None:
        """
        Finalize a discovery run after all windows are processed.

        Args:
            run: The discovery run to finalize
        """
        # Count total candidates
        candidates = await self.candidate_repository.get_by_run_id(run.id)
        run.total_candidates = len(candidates)

        # Count processed windows
        windows = await self.window_repository.get_by_run_id(run.id)
        run.processed_windows = sum(1 for w in windows if w.status == "completed")

        # Update run status
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
