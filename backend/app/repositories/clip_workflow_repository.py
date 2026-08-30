"""ClipWorkflow repository."""

import hashlib
import json
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipWorkflow
from app.repositories.base import BaseRepository


class ClipWorkflowRepository(BaseRepository[ClipWorkflow]):
    """Repository for ClipWorkflow entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, ClipWorkflow)

    async def get_by_source(self, source_id: UUID) -> list[ClipWorkflow]:
        """Get workflows by source ID."""
        stmt = select(ClipWorkflow).where(ClipWorkflow.source_id == source_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_status(self, status: str, limit: int = 100) -> list[ClipWorkflow]:
        """Get workflows by status."""
        stmt = select(ClipWorkflow).where(ClipWorkflow.status == status).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_idempotency_key(
        self, source_id: UUID, idempotency_fingerprint: str
    ) -> ClipWorkflow | None:
        """
        Get workflow by source ID and idempotency fingerprint.

        For now, we use source_id as the unique constraint for MVP.
        Future versions may include more complex idempotency logic.
        """
        stmt = select(ClipWorkflow).where(ClipWorkflow.source_id == source_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def compute_fingerprint(source_id: UUID) -> str:
        """
        Compute idempotency fingerprint for workflow creation.

        For MVP, this is simply the source_id.
        Future versions may include additional parameters.
        """
        data = {"source_id": str(source_id)}
        canonical = json.dumps(data, sort_keys=True)
        return hashlib.sha256(canonical.encode()).hexdigest()
