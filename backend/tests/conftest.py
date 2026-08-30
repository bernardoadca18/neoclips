"""Pytest configuration and fixtures."""

import asyncio
from typing import AsyncGenerator, Generator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.entities import ClipSource, ClipWorkflow, SourcePolicy


# Test database URL (use SQLite for unit tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine():
    """Create a test database engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

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
def sample_policy_data():
    """Sample policy data for testing."""
    return {
        "id": uuid4(),
        "name": "Test Policy",
        "version": "1.0",
        "verification_status": "verified",
        "commercial_use_allowed": True,
        "derivatives_allowed": True,
        "monetization_allowed": True,
    }


@pytest.fixture
def sample_source_data(sample_policy_data):
    """Sample source data for testing."""
    return {
        "id": uuid4(),
        "source_policy_id": sample_policy_data["id"],
        "mode": "safe_automated",
        "title": "Test Source",
        "rights_status": "verified",
        "status": "pending",
    }


@pytest.fixture
def sample_workflow_data(sample_source_data):
    """Sample workflow data for testing."""
    return {
        "id": uuid4(),
        "source_id": sample_source_data["id"],
        "status": "created",
        "attempt_count": 0,
    }
