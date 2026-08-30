"""Base service class."""

from typing import Generic, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.base import BaseRepository

RepositoryType = TypeVar("RepositoryType", bound=BaseRepository)


class BaseService(Generic[RepositoryType]):
    """Base service with common operations."""

    def __init__(self, session: AsyncSession, repository: RepositoryType) -> None:
        self.session = session
        self.repository = repository
