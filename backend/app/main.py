"""NeoClips FastAPI application."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routers import (
    discovery_router,
    editorial_router,
    health_router,
    policies_router,
    sources_router,
    workflows_router,
)
from app.core.config import get_settings
from app.core.database import close_database_connection
from app.core.logging_config import setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler."""
    # Startup
    setup_logging()

    yield

    # Shutdown
    await close_database_connection()


app = FastAPI(
    title="NeoClips",
    description="Clip discovery and production engine",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)

# Include routers
app.include_router(health_router)
app.include_router(policies_router)
app.include_router(sources_router)
app.include_router(workflows_router)
app.include_router(discovery_router)
app.include_router(editorial_router)


@app.get("/", include_in_schema=False)
async def root() -> dict[str, str]:
    """Root endpoint redirects to docs."""
    return {"message": "NeoClips API", "docs": "/docs"}
