"""Service for retrieving bounded transcript context around clip candidates.

Provides context retrieval via Media Indexer API - never accesses the full
transcript, only the bounded segments needed for editorial analysis.
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient
from app.models.entities import ClipCandidate, ClipSource, DiscoveryRun

logger = logging.getLogger(__name__)


class CandidateContextError(Exception):
    """Base error for candidate context service."""

    pass


class CandidateNotFoundError(CandidateContextError):
    """Raised when candidate is not found."""

    pass


class SourceNotFoundError(CandidateContextError):
    """Raised when source is not found."""

    pass


class TranscriptionNotFoundError(CandidateContextError):
    """Raised when transcription is not found."""

    pass


class CandidateContextService:
    """
    Service for retrieving bounded transcript context around candidates.

    Fetches only the necessary segments from Media Indexer - never the
    full transcript. Uses configurable context_before_seconds and
    context_after_seconds to bound the retrieval.
    """

    def __init__(
        self,
        session: AsyncSession,
        media_indexer_client: MediaIndexerClient,
        default_context_before: float = 45.0,
        default_context_after: float = 40.0,
    ) -> None:
        self.session = session
        self.media_indexer_client = media_indexer_client
        self.default_context_before = default_context_before
        self.default_context_after = default_context_after

    async def get_candidate_context(
        self,
        candidate_id: UUID,
        context_before_seconds: float | None = None,
        context_after_seconds: float | None = None,
    ) -> dict[str, Any]:
        """
        Get bounded transcript context around a candidate.

        Args:
            candidate_id: UUID of the clip candidate
            context_before_seconds: Seconds of context before candidate (default: 45.0)
            context_after_seconds: Seconds of context after candidate (default: 40.0)

        Returns:
            Dict with:
                - candidate_id: UUID
                - candidate_segments: list of segment dicts
                - context_before_segments: list of segment dicts
                - context_after_segments: list of segment dicts
                - transcription_id: UUID
                - source_id: UUID

        Raises:
            CandidateNotFoundError: If candidate doesn't exist
            SourceNotFoundError: If source doesn't exist
            TranscriptionNotFoundError: If transcription_id is missing
        """
        # Get candidate with run and workflow to find source
        result = await self.session.execute(
            select(ClipCandidate)
            .where(ClipCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {candidate_id} not found")

        # Get the discovery run to find workflow_id
        run_result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == candidate.run_id)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            raise CandidateNotFoundError(f"Run {candidate.run_id} not found")

        # Get the source via workflow
        from app.models.entities import ClipWorkflow
        workflow_result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == run.workflow_id)
        )
        workflow = workflow_result.scalar_one_or_none()

        if not workflow:
            raise SourceNotFoundError(f"Workflow {run.workflow_id} not found")

        source_result = await self.session.execute(
            select(ClipSource).where(ClipSource.id == workflow.source_id)
        )
        source = source_result.scalar_one_or_none()

        if not source:
            raise SourceNotFoundError(f"Source {workflow.source_id} not found")

        if not source.transcription_id:
            raise TranscriptionNotFoundError(
                f"Source {source.id} has no transcription_id"
            )

        # Use provided context bounds or defaults
        before = context_before_seconds or self.default_context_before
        after = context_after_seconds or self.default_context_after

        # Calculate time range for context retrieval
        candidate_start = candidate.canonical_start_seconds
        candidate_end = candidate.canonical_end_seconds

        context_start = max(0.0, candidate_start - before)
        context_end = candidate_end + after

        # Fetch segments from Media Indexer using bounded temporal query
        segments = await self.media_indexer_client.get_transcript_segments_by_time(
            transcription_id=source.transcription_id,
            start_seconds=context_start,
            end_seconds=context_end,
        )

        # Categorize segments into before, candidate, after
        candidate_segments = []
        context_before_segments = []
        context_after_segments = []

        for seg in segments:
            seg_start = seg.start_seconds
            seg_end = seg.end_seconds

            # Determine segment category based on overlap
            seg_dict = {
                "id": seg.id,
                "start_seconds": seg_start,
                "end_seconds": seg_end,
                "text": seg.text,
            }

            # Check if segment is within candidate bounds
            if seg_start >= candidate_start and seg_end <= candidate_end:
                candidate_segments.append(seg_dict)
            elif seg_end <= candidate_start:
                context_before_segments.append(seg_dict)
            elif seg_start >= candidate_end:
                context_after_segments.append(seg_dict)
            else:
                # Segment overlaps with candidate boundary - include in candidate
                candidate_segments.append(seg_dict)

        return {
            "candidate_id": str(candidate_id),
            "candidate_segments": candidate_segments,
            "context_before_segments": context_before_segments,
            "context_after_segments": context_after_segments,
            "transcription_id": str(source.transcription_id),
            "source_id": str(source.id),
        }

    async def get_segments_for_analysis(
        self,
        candidate_id: UUID,
        context_before_seconds: float | None = None,
        context_after_seconds: float | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """
        Get segments formatted for LLM analysis.

        Convenience method that returns just the segments needed for
        the NineRouterEditorialProvider.

        Args:
            candidate_id: UUID of the clip candidate
            context_before_seconds: Seconds of context before candidate
            context_after_seconds: Seconds of context after candidate

        Returns:
            Tuple of (candidate_segments, context_before, context_after)
        """
        context = await self.get_candidate_context(
            candidate_id=candidate_id,
            context_before_seconds=context_before_seconds,
            context_after_seconds=context_after_seconds,
        )

        return (
            context["candidate_segments"],
            context["context_before_segments"],
            context["context_after_segments"],
        )


__all__ = [
    "CandidateContextService",
    "CandidateContextError",
    "CandidateNotFoundError",
    "SourceNotFoundError",
    "TranscriptionNotFoundError",
]
