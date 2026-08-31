"""Base repository with common CRUD operations."""

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base


class BaseRepository[ModelType: Base]:
    """Base repository with common CRUD operations."""

    def __init__(self, session: AsyncSession, model: type[ModelType]) -> None:
        self.session = session
        self.model = model

    async def get_by_id(self, id: UUID) -> ModelType | None:
        """Get entity by ID."""
        stmt = select(self.model).where(self.model.id == id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    # Alias for backwards compatibility
    get = get_by_id

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[ModelType]:
        """Get all entities with pagination."""
        stmt = select(self.model).limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # Alias for consistency
    list = get_all

    async def create(self, data: dict[str, Any]) -> ModelType:
        """Create new entity."""
        entity = self.model(**data)
        self.session.add(entity)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def update(self, entity: ModelType, data: dict[str, Any] | None = None) -> ModelType:
        """Update entity.

        If data is provided, updates fields from the dict.
        If data is None, assumes entity was already modified in-place.
        """
        if data is not None:
            for key, value in data.items():
                setattr(entity, key, value)
        await self.session.flush()
        await self.session.refresh(entity)
        return entity

    async def delete(self, entity: ModelType) -> None:
        """Delete entity."""
        await self.session.delete(entity)
        await self.session.flush()
