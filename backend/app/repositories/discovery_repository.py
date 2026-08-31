"""Repository for DiscoveryRun, DiscoveryWindow, and ClipCandidate."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipCandidate, DiscoveryRun, DiscoveryWindow
from app.repositories.base import BaseRepository


class DiscoveryRunRepository(BaseRepository[DiscoveryRun]):
    """Repository for DiscoveryRun entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DiscoveryRun)

    async def get_by_workflow_id(self, workflow_id: UUID) -> list[DiscoveryRun]:
        """Get all discovery runs for a workflow."""
        result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.workflow_id == workflow_id)
        )
        return list(result.scalars().all())

    async def get_latest_by_workflow_id(self, workflow_id: UUID) -> DiscoveryRun | None:
        """Get the latest discovery run for a workflow."""
        result = await self.session.execute(
            select(DiscoveryRun)
            .where(DiscoveryRun.workflow_id == workflow_id)
            .order_by(DiscoveryRun.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class DiscoveryWindowRepository(BaseRepository[DiscoveryWindow]):
    """Repository for DiscoveryWindow entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DiscoveryWindow)

    async def get_by_run_id(self, run_id: UUID) -> list[DiscoveryWindow]:
        """Get all windows for a discovery run."""
        result = await self.session.execute(
            select(DiscoveryWindow)
            .where(DiscoveryWindow.run_id == run_id)
            .order_by(DiscoveryWindow.window_index)
        )
        return list(result.scalars().all())

    async def get_pending_by_run_id(self, run_id: UUID) -> list[DiscoveryWindow]:
        """Get pending windows for a discovery run."""
        result = await self.session.execute(
            select(DiscoveryWindow)
            .where(DiscoveryWindow.run_id == run_id)
            .where(DiscoveryWindow.status == "pending")
            .order_by(DiscoveryWindow.window_index)
        )
        return list(result.scalars().all())


class ClipCandidateRepository(BaseRepository[ClipCandidate]):
    """Repository for ClipCandidate entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ClipCandidate)

    async def get_by_run_id(self, run_id: UUID) -> list[ClipCandidate]:
        """Get all candidates for a discovery run."""
        result = await self.session.execute(
            select(ClipCandidate)
            .where(ClipCandidate.run_id == run_id)
            .order_by(ClipCandidate.score_v1.desc().nulls_last())
        )
        return list(result.scalars().all())

    async def get_non_duplicate_by_run_id(self, run_id: UUID) -> list[ClipCandidate]:
        """Get non-duplicate candidates for a discovery run, sorted by score."""
        result = await self.session.execute(
            select(ClipCandidate)
            .where(ClipCandidate.run_id == run_id)
            .where(ClipCandidate.is_duplicate == False)
            .order_by(ClipCandidate.score_v1.desc().nulls_last())
        )
        return list(result.scalars().all())

    async def get_selected_by_run_id(self, run_id: UUID) -> list[ClipCandidate]:
        """Get selected candidates for a discovery run."""
        result = await self.session.execute(
            select(ClipCandidate)
            .where(ClipCandidate.run_id == run_id)
            .where(ClipCandidate.selected == True)
            .order_by(ClipCandidate.selection_rank)
        )
        return list(result.scalars().all())

    async def get_by_time_range(
        self, run_id: UUID, start_seconds: float, end_seconds: float
    ) -> list[ClipCandidate]:
        """Get candidates that overlap with a time range."""
        result = await self.session.execute(
            select(ClipCandidate)
            .where(ClipCandidate.run_id == run_id)
            .where(ClipCandidate.canonical_start_seconds < end_seconds)
            .where(ClipCandidate.canonical_end_seconds > start_seconds)
        )
        return list(result.scalars().all())
