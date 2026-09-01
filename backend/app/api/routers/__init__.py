"""NeoClips API routers."""

from app.api.routers.discovery import router as discovery_router
from app.api.routers.editorial import router as editorial_router
from app.api.routers.health import router as health_router
from app.api.routers.policies import router as policies_router
from app.api.routers.sources import router as sources_router
from app.api.routers.workflows import router as workflows_router

__all__ = [
    "discovery_router",
    "editorial_router",
    "health_router",
    "policies_router",
    "sources_router",
    "workflows_router",
]
