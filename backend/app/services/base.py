"""Base service class."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository


class BaseService[RepositoryType: BaseRepository[Any]]:
    """Base service with common operations."""

    def __init__(self, session: AsyncSession, repository: RepositoryType) -> None:
        self.session = session
        self.repository = repository
