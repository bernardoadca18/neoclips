"""ClipWorkflow repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipWorkflow
from app.repositories.base import BaseRepository


class ClipWorkflowRepository(BaseRepository[ClipWorkflow]):
    """Repository for ClipWorkflow entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ClipWorkflow)

    async def get_by_source(self, source_id: UUID) -> ClipWorkflow | None:
        """Get workflow by source ID (unique constraint ensures max one)."""
        stmt = select(ClipWorkflow).where(ClipWorkflow.source_id == source_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_status(self, status: str, limit: int = 100) -> list[ClipWorkflow]:
        """Get workflows by status."""
        stmt = select(ClipWorkflow).where(ClipWorkflow.status == status).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_idempotency_key(self, idempotency_key: str) -> ClipWorkflow | None:
        """Get workflow by idempotency key."""
        stmt = select(ClipWorkflow).where(ClipWorkflow.idempotency_key == idempotency_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
