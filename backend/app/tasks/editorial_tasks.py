"""Celery tasks for editorial suitability analysis (Stage 4).

Design principles:
- One-shot execution: Each task performs the LLM call once
- State in PostgreSQL: All state transitions persisted
- Error handling: Failures are recorded in analysis record
"""

import asyncio
import logging
from typing import Any
from uuid import UUID

from app.core.celery_app import celery_app
from app.core.database import async_session_factory

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.execute_editorial_analysis")  # type: ignore[untyped-decorator]
def execute_editorial_analysis(analysis_id: str) -> dict[str, Any]:
    """
    Execute editorial suitability analysis.

    Performs the LLM call via 9Router and updates the analysis record
    with results. This task is dispatched after analysis creation.

    Args:
        analysis_id: UUID of the EditorialSuitabilityAnalysis

    Returns:
        Dict with status and analysis_id
    """
    return asyncio.run(_execute_editorial_analysis_async(UUID(analysis_id)))


async def _execute_editorial_analysis_async(analysis_id: UUID) -> dict[str, Any]:
    """Async implementation of execute_editorial_analysis task."""
    from sqlalchemy import select

    from app.clients.media_indexer_client import MediaIndexerClient
    from app.core.config import settings
    from app.models.entities import EditorialSuitabilityAnalysis
    from app.services.candidate_context_service import CandidateContextService
    from app.services.editorial_analysis_service import (
        EditorialAnalysisError,
        EditorialAnalysisService,
    )
    from app.services.ninerouter_editorial_provider import NineRouterEditorialProvider

    async with async_session_factory() as session:
        # Check analysis exists
        result = await session.execute(
            select(EditorialSuitabilityAnalysis).where(
                EditorialSuitabilityAnalysis.id == analysis_id
            )
        )
        analysis = result.scalar_one_or_none()

        if not analysis:
            logger.error(
                "editorial_analysis_not_found",
                extra={"analysis_id": str(analysis_id)},
            )
            return {"status": "failed", "error": "Analysis not found"}

        if analysis.status == "completed":
            logger.info(
                "editorial_analysis_already_completed",
                extra={"analysis_id": str(analysis_id)},
            )
            return {"status": "skipped", "reason": "already_completed"}

        # Create services
        media_indexer_client = MediaIndexerClient(
            base_url=settings.media_indexer_base_url,
            timeout_seconds=settings.media_indexer_timeout_seconds,
        )
        context_service = CandidateContextService(
            session=session,
            media_indexer_client=media_indexer_client,
        )
        editorial_provider = NineRouterEditorialProvider()

        service = EditorialAnalysisService(
            session=session,
            context_service=context_service,
            editorial_provider=editorial_provider,
        )

        try:
            updated_analysis = await service.execute_analysis(analysis_id)
            logger.info(
                "editorial_analysis_completed",
                extra={
                    "analysis_id": str(analysis_id),
                    "strategy": updated_analysis.recommended_strategy,
                },
            )
            return {"status": "success", "analysis_id": str(analysis_id)}

        except EditorialAnalysisError as e:
            logger.error(
                "editorial_analysis_failed",
                extra={
                    "analysis_id": str(analysis_id),
                    "error": str(e),
                },
            )
            return {"status": "failed", "error": str(e)}

        except Exception as e:
            logger.exception(
                "editorial_analysis_unexpected_error",
                extra={"analysis_id": str(analysis_id)},
            )
            return {"status": "failed", "error": f"Unexpected error: {e}"}


__all__ = ["execute_editorial_analysis"]
