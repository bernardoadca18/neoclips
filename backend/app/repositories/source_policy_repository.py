"""SourcePolicy repository."""


from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import SourcePolicy
from app.repositories.base import BaseRepository


class SourcePolicyRepository(BaseRepository[SourcePolicy]):
    """Repository for SourcePolicy entities."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, SourcePolicy)

    async def get_by_name_version(self, name: str, version: str) -> SourcePolicy | None:
        """Get policy by name and version."""
        stmt = select(SourcePolicy).where(
            SourcePolicy.name == name,
            SourcePolicy.version == version,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_verified_policies(self) -> list[SourcePolicy]:
        """Get all verified policies."""
        stmt = select(SourcePolicy).where(SourcePolicy.verification_status == "verified")
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
