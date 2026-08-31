"""ClipSource repository."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipSource
from app.repositories.base import BaseRepository


class ClipSourceRepository(BaseRepository[ClipSource]):
    """Repository for ClipSource entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ClipSource)

    async def get_by_status(self, status: str, limit: int = 100) -> list[ClipSource]:
        """Get sources by status."""
        stmt = select(ClipSource).where(ClipSource.status == status).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_policy(self, policy_id: UUID) -> list[ClipSource]:
        """Get sources by policy ID."""
        stmt = select(ClipSource).where(ClipSource.source_policy_id == policy_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_idempotency_key(self, idempotency_key: str) -> ClipSource | None:
        """Get source by idempotency key."""
        stmt = select(ClipSource).where(ClipSource.idempotency_key == idempotency_key)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
