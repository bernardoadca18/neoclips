"""Pytest configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from app.main import app
from app.models.base import Base


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    """Start a PostgreSQL container for integration tests."""
    container = PostgresContainer("postgres:16-alpine")
    container.start()
    yield container
    container.stop()


@pytest_asyncio.fixture
async def engine(postgres_container: PostgresContainer):
    """Create a test database engine with real PostgreSQL."""
    from sqlalchemy.ext.asyncio import create_async_engine

    # Convert postgres container URL to asyncpg format
    url = postgres_container.get_connection_url()
    # Handle both postgresql:// and postgresql+psycopg2:// formats
    async_url = url.replace("postgresql+psycopg2://", "postgresql+asyncpg://")
    async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")

    engine = create_async_engine(async_url, echo=False)

    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Cleanup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session."""
    async_session = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session() as session:
        yield session


@pytest.fixture
def sample_policy_data() -> dict[str, Any]:
    """Sample policy data for testing."""
    return {
        "id": uuid4(),
        "name": "Test Policy",
        "version": "1.0",
        "verification_status": "unverified",
        "commercial_use_allowed": False,
        "derivatives_allowed": False,
        "monetization_allowed": False,
        "attribution_required": False,
        "embargo_seconds": 0,
    }


@pytest.fixture
def sample_source_data() -> dict[str, Any]:
    """Sample source data for testing."""
    return {
        "id": uuid4(),
        "mode": "manual_override",
        "operator_acknowledged": True,
        "title": "Test Source",
        "rights_status": "unverified",
        "status": "pending",
    }


@pytest.fixture
def sample_workflow_data(sample_source_data: dict[str, Any]) -> dict[str, Any]:
    """Sample workflow data for testing."""
    return {
        "id": uuid4(),
        "source_id": sample_source_data["id"],
        "status": "created",
        "attempt_count": 0,
    }


@pytest_asyncio.fixture
async def async_client(session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create an async HTTP client for testing."""
    from app.core.database import get_session

    # Override the dependency
    async def override_get_session():
        yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()
