"""Health check endpoints."""

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from redis import asyncio as aioredis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Liveness health response."""

    status: str


class DependencyHealth(BaseModel):
    """Health status of a dependency."""

    postgres: str
    redis: str


class ReadinessResponse(BaseModel):
    """Readiness health response."""

    status: str
    dependencies: DependencyHealth


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Liveness check",
    description="Returns 200 if the process is running. Does NOT check dependencies.",
)
async def health() -> HealthResponse:
    """
    Liveness check.

    Returns 200 if the process is running.
    Does NOT check dependencies.
    """
    return HealthResponse(status="ok")


async def _check_readiness(
    session: AsyncSession,
) -> ReadinessResponse:
    """
    Shared readiness logic for both /health/ready and /health/readiness.

    Returns 200 only if all dependencies are healthy.
    Returns 503 with degraded status if any dependency is unavailable.
    """
    settings = get_settings()

    # Check PostgreSQL
    try:
        await session.execute(text("SELECT 1"))
        postgres_status = "ready"
    except Exception:
        postgres_status = "unavailable"

    # Check Redis
    try:
        redis = aioredis.from_url(str(settings.redis_url))
        await redis.ping()
        await redis.close()
        redis_status = "ready"
    except Exception:
        redis_status = "unavailable"

    # Determine overall status
    all_healthy = postgres_status == "ready" and redis_status == "ready"
    overall_status = "ready" if all_healthy else "degraded"

    response = ReadinessResponse(
        status=overall_status,
        dependencies=DependencyHealth(
            postgres=postgres_status,
            redis=redis_status,
        ),
    )

    # Return 503 if any dependency is unavailable
    if not all_healthy:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=response.model_dump(),
        )

    return response


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness check (alias)",
    description="Returns 200 only if all dependencies are healthy. Alias for /health/readiness.",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "One or more dependencies are unavailable",
            "model": ReadinessResponse,
        }
    },
)
async def ready(
    session: AsyncSession = Depends(get_session),
) -> ReadinessResponse:
    """
    Readiness check (NeoVids standard endpoint).
    """
    return await _check_readiness(session)


@router.get(
    "/health/readiness",
    response_model=ReadinessResponse,
    status_code=status.HTTP_200_OK,
    summary="Readiness check",
    description="Returns 200 only if all dependencies are healthy.",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "One or more dependencies are unavailable",
            "model": ReadinessResponse,
        }
    },
)
async def readiness(
    session: AsyncSession = Depends(get_session),
) -> ReadinessResponse:
    """
    Readiness check.

    Returns 200 only if all dependencies are healthy.
    Returns 503 with degraded status if any dependency is unavailable.
    """
    return await _check_readiness(session)
