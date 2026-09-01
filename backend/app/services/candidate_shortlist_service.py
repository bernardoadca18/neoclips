"""Service for retrieving bounded candidate shortlist from a DiscoveryRun.

Provides an ordered, bounded view of the best candidates from a discovery run,
suitable for editorial review and selection.
"""

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.models.entities import ClipCandidate, DiscoveryRun, EditorialSuitabilityAnalysis, ShortEditorialPlan

logger = logging.getLogger(__name__)


class ShortlistError(Exception):
    """Base error for shortlist service."""

    pass


class RunNotFoundError(ShortlistError):
    """Raised when discovery run is not found."""

    pass


class RunNotTerminalError(ShortlistError):
    """Raised when run is not in a terminal state."""

    pass


class CandidateShortlistService:
    """
    Service for retrieving candidate shortlist from a discovery run.

    Returns candidates ordered by score_v1 descending, bounded by limit.
    Includes metadata about whether each candidate has analysis or plan.
    """

    def __init__(
        self,
        session: AsyncSession,
        default_limit: int = 50,
    ) -> None:
        self.session = session
        self.default_limit = default_limit

    async def get_shortlist(
        self,
        run_id: UUID,
        limit: int | None = None,
        include_duplicates: bool = False,
    ) -> dict:
        """
        Get the candidate shortlist for a discovery run.

        Args:
            run_id: UUID of the discovery run
            limit: Maximum candidates to return (default: 50)
            include_duplicates: Whether to include duplicate candidates

        Returns:
            Dict with:
                - run_id: UUID
                - workflow_id: UUID
                - total_candidates: int
                - returned_count: int
                - candidates: list of CandidateShortlistItem dicts

        Raises:
            RunNotFoundError: If run doesn't exist
            RunNotTerminalError: If run is not in terminal state
        """
        # Get run and verify it exists
        run_result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == run_id)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            raise RunNotFoundError(f"Run {run_id} not found")

        # Check if run is in terminal state
        terminal_states = {"completed", "completed_with_errors", "failed"}
        if run.status not in terminal_states:
            raise RunNotTerminalError(
                f"Run {run_id} is not in terminal state (current: {run.status})"
            )

        # Build query for candidates
        limit = limit or self.default_limit

        # Query candidates with score, excluding duplicates by default
        query = (
            select(ClipCandidate)
            .where(ClipCandidate.run_id == run_id)
            .order_by(ClipCandidate.score_v1.desc().nulls_last())
            .limit(limit)
        )

        if not include_duplicates:
            query = query.where(ClipCandidate.is_duplicate == False)

        result = await self.session.execute(query)
        candidates = result.scalars().all()

        # Get counts for each candidate's analysis/plan existence
        candidate_ids = [c.id for c in candidates]

        # Subquery for analysis existence
        analysis_counts = {}
        if candidate_ids:
            analysis_result = await self.session.execute(
                select(
                    EditorialSuitabilityAnalysis.candidate_id,
                    func.count(EditorialSuitabilityAnalysis.id).label("count")
                )
                .where(EditorialSuitabilityAnalysis.candidate_id.in_(candidate_ids))
                .group_by(EditorialSuitabilityAnalysis.candidate_id)
            )
            analysis_counts = {row.candidate_id: row.count for row in analysis_result}

        # Subquery for plan existence
        plan_counts = {}
        if candidate_ids:
            plan_result = await self.session.execute(
                select(
                    ShortEditorialPlan.candidate_id,
                    func.count(ShortEditorialPlan.id).label("count")
                )
                .where(ShortEditorialPlan.candidate_id.in_(candidate_ids))
                .group_by(ShortEditorialPlan.candidate_id)
            )
            plan_counts = {row.candidate_id: row.count for row in plan_result}

        # Build response
        shortlist_items = []
        for candidate in candidates:
            shortlist_items.append({
                "id": str(candidate.id),
                "run_id": str(candidate.run_id),
                "canonical_start_seconds": candidate.canonical_start_seconds,
                "canonical_end_seconds": candidate.canonical_end_seconds,
                "duration_seconds": candidate.duration_seconds,
                "title": candidate.title,
                "summary": candidate.summary,
                "hook_type": candidate.hook_type,
                "score_v1": candidate.score_v1,
                "discovery_rank": candidate.discovery_rank,
                "is_duplicate": candidate.is_duplicate,
                "selected": candidate.selected,
                "selection_rank": candidate.selection_rank,
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "has_analysis": candidate.id in analysis_counts,
                "has_plan": candidate.id in plan_counts,
            })

        # Get total candidates count
        total_result = await self.session.execute(
            select(func.count(ClipCandidate.id)).where(ClipCandidate.run_id == run_id)
        )
        total_count = total_result.scalar() or 0

        return {
            "run_id": str(run_id),
            "workflow_id": str(run.workflow_id),
            "total_candidates": total_count,
            "returned_count": len(shortlist_items),
            "candidates": shortlist_items,
        }

    async def get_selected_candidates(self, run_id: UUID) -> list[dict]:
        """
        Get all selected candidates for a run.

        Args:
            run_id: UUID of the discovery run

        Returns:
            List of candidate dicts with selection info
        """
        result = await self.session.execute(
            select(ClipCandidate)
            .where(ClipCandidate.run_id == run_id)
            .where(ClipCandidate.selected == True)
            .order_by(ClipCandidate.selection_rank.asc().nulls_last())
        )
        candidates = result.scalars().all()

        return [
            {
                "id": str(c.id),
                "selection_rank": c.selection_rank,
                "score_v1": c.score_v1,
                "title": c.title,
            }
            for c in candidates
        ]


__all__ = [
    "CandidateShortlistService",
    "ShortlistError",
    "RunNotFoundError",
    "RunNotTerminalError",
]
