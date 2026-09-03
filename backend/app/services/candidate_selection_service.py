"""Service for managing candidate selection state.

Handles manual select/unselect operations with validation rules:
- Cannot select duplicate candidates
- Run must be in terminal state for selection
- Selection rank management
"""

import logging
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipCandidate, DiscoveryRun

logger = logging.getLogger(__name__)


class SelectionError(Exception):
    """Base error for selection service."""

    pass


class CandidateNotFoundError(SelectionError):
    """Raised when candidate is not found."""

    pass


class DuplicateSelectionError(SelectionError):
    """Raised when trying to select a duplicate candidate."""

    pass


class RunNotTerminalError(SelectionError):
    """Raised when run is not in terminal state."""

    pass


class CandidateSelectionService:
    """
    Service for managing candidate selection state.

    Enforces validation rules:
    - Duplicate candidates cannot be selected
    - Run must be in terminal state (completed, completed_with_errors only - NOT failed)
    - Selection rank is optional but must be >= 1

    NOTE: "failed" is excluded from TERMINAL_STATES because fully failed runs
    have no valid candidates to select.
    """

    # NOTE: "failed" is excluded - fully failed runs have no valid candidates
    TERMINAL_STATES = {"completed", "completed_with_errors"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def select_candidate(
        self,
        candidate_id: UUID,
        selection_rank: int | None = None,
    ) -> ClipCandidate:
        """
        Mark a candidate as selected.

        Args:
            candidate_id: UUID of the candidate
            selection_rank: Optional rank for ordering (must be >= 1)

        Returns:
            Updated ClipCandidate

        Raises:
            CandidateNotFoundError: If candidate doesn't exist
            DuplicateSelectionError: If candidate is marked as duplicate
            RunNotTerminalError: If run is not in terminal state
        """
        # Get candidate
        result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {candidate_id} not found")

        # Check if duplicate
        if candidate.is_duplicate:
            raise DuplicateSelectionError(
                f"Candidate {candidate_id} is marked as duplicate and cannot be selected"
            )

        # Verify run is in terminal state
        run_result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == candidate.run_id)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            raise SelectionError(f"Run {candidate.run_id} not found")

        if run.status not in self.TERMINAL_STATES:
            raise RunNotTerminalError(
                f"Run {run.id} is not in terminal state (current: {run.status}). "
                f"Selection is only allowed after discovery completes."
            )

        # Update selection state
        candidate.selected = True

        if selection_rank is not None:
            if selection_rank < 1:
                raise SelectionError("selection_rank must be >= 1")
            candidate.selection_rank = selection_rank

        await self.session.commit()
        await self.session.refresh(candidate)

        logger.info(f"Candidate {candidate_id} selected with rank {selection_rank}")
        return candidate

    async def unselect_candidate(self, candidate_id: UUID) -> ClipCandidate:
        """
        Mark a candidate as not selected.

        Args:
            candidate_id: UUID of the candidate

        Returns:
            Updated ClipCandidate

        Raises:
            CandidateNotFoundError: If candidate doesn't exist
        """
        # Get candidate
        result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {candidate_id} not found")

        # Update selection state
        candidate.selected = False
        candidate.selection_rank = None

        await self.session.commit()
        await self.session.refresh(candidate)

        logger.info(f"Candidate {candidate_id} unselected")
        return candidate

    async def set_selection_rank(
        self,
        candidate_id: UUID,
        selection_rank: int,
    ) -> ClipCandidate:
        """
        Set the selection rank for a candidate.

        Args:
            candidate_id: UUID of the candidate
            selection_rank: Rank value (must be >= 1)

        Returns:
            Updated ClipCandidate

        Raises:
            CandidateNotFoundError: If candidate doesn't exist
            SelectionError: If rank is invalid
        """
        if selection_rank < 1:
            raise SelectionError("selection_rank must be >= 1")

        # Get candidate
        result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {candidate_id} not found")

        candidate.selection_rank = selection_rank

        await self.session.commit()
        await self.session.refresh(candidate)

        logger.info(f"Candidate {candidate_id} rank set to {selection_rank}")
        return candidate

    async def get_selection_state(self, candidate_id: UUID) -> dict:
        """
        Get the selection state for a candidate.

        Args:
            candidate_id: UUID of the candidate

        Returns:
            Dict with selection info
        """
        result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {candidate_id} not found")

        return {
            "candidate_id": str(candidate_id),
            "selected": candidate.selected,
            "selection_rank": candidate.selection_rank,
            "is_duplicate": candidate.is_duplicate,
        }

    async def bulk_selection(
        self,
        candidate_ids: list[UUID],
        selected: bool,
    ) -> list[dict]:
        """
        Select or unselect multiple candidates.

        Args:
            candidate_ids: List of candidate UUIDs
            selected: True to select, False to unselect

        Returns:
            List of result dicts with candidate_id and status
        """
        results = []

        for candidate_id in candidate_ids:
            try:
                if selected:
                    await self.select_candidate(candidate_id)
                else:
                    await self.unselect_candidate(candidate_id)
                results.append({
                    "candidate_id": str(candidate_id),
                    "success": True,
                    "selected": selected,
                })
            except SelectionError as e:
                results.append({
                    "candidate_id": str(candidate_id),
                    "success": False,
                    "error": str(e),
                })

        return results


__all__ = [
    "CandidateSelectionService",
    "SelectionError",
    "CandidateNotFoundError",
    "DuplicateSelectionError",
    "RunNotTerminalError",
]
