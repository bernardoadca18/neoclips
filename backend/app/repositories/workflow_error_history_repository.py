"""WorkflowErrorHistory repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import WorkflowErrorHistory
from app.repositories.base import BaseRepository


class WorkflowErrorHistoryRepository(BaseRepository[WorkflowErrorHistory]):
    """Repository for WorkflowErrorHistory entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, WorkflowErrorHistory)

    async def get_by_workflow(
        self, workflow_id: UUID, limit: int = 100
    ) -> list[WorkflowErrorHistory]:
        """Get error history for a workflow, ordered by creation time."""
        stmt = (
            select(WorkflowErrorHistory)
            .where(WorkflowErrorHistory.workflow_id == workflow_id)
            .order_by(WorkflowErrorHistory.created_at.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
