"""Service for orchestrating editorial suitability analysis.

Manages the workflow of analyzing clip candidates for editorial suitability,
including idempotency, transaction boundaries, and Celery task dispatch.
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipCandidate, EditorialSuitabilityAnalysis
from app.services.candidate_context_service import CandidateContextService
from app.services.ninerouter_editorial_provider import (
    CandidateContext,
    NineRouterEditorialError,
    NineRouterEditorialProvider,
)

logger = logging.getLogger(__name__)


class EditorialAnalysisError(Exception):
    """Base error for editorial analysis service."""

    pass


class AnalysisAlreadyExistsError(EditorialAnalysisError):
    """Raised when analysis already exists for candidate."""

    pass


class CandidateNotReadyError(EditorialAnalysisError):
    """Raised when candidate is not ready for analysis."""

    pass


class EditorialAnalysisService:
    """
    Service for managing editorial suitability analysis workflow.

    Handles:
    - Idempotency via request_fingerprint
    - Transaction boundaries (commit before LLM call)
    - Celery task dispatch for async execution
    - Persistence of analysis results
    """

    STRATEGY_ID = "editorial_suitability"
    STRATEGY_VERSION = "1.0.0"
    PROMPT_ID = "editorial_suitability_v1"
    PROMPT_VERSION = "1.0.0"

    def __init__(
        self,
        session: AsyncSession,
        context_service: CandidateContextService,
        editorial_provider: NineRouterEditorialProvider | None = None,
    ) -> None:
        self.session = session
        self.context_service = context_service
        self.editorial_provider = editorial_provider or NineRouterEditorialProvider()

    def _compute_request_fingerprint(
        self,
        candidate_id: UUID,
        source_id: UUID,
        transcription_id: UUID,
        context_before: float,
        context_after: float,
        strategy_id: str,
        strategy_version: str,
        prompt_id: str,
        prompt_version: str,
        prompt_hash: str,
        requested_combo: str,
    ) -> str:
        """Compute SHA-256 fingerprint for idempotency.

        Includes all parameters that affect analysis identity:
        - candidate_id: the candidate being analyzed
        - source_id/transcription_id: media identity
        - context_before/after: context window configuration
        - strategy_id/version: analysis strategy identity
        - prompt_id/version/hash: prompt configuration
        - requested_combo: LLM combo used
        """
        data = json.dumps({
            "candidate_id": str(candidate_id),
            "source_id": str(source_id),
            "transcription_id": str(transcription_id),
            "context_before": context_before,
            "context_after": context_after,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "prompt_id": prompt_id,
            "prompt_version": prompt_version,
            "prompt_hash": prompt_hash,
            "requested_combo": requested_combo,
        }, sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    async def get_or_create_analysis(
        self,
        candidate_id: UUID,
        context_before_seconds: float = 45.0,
        context_after_seconds: float = 40.0,
    ) -> EditorialSuitabilityAnalysis:
        """
        Get existing analysis or create a new one for the candidate.

        This is the main entry point for the analysis workflow. It handles
        idempotency by checking for existing analyses with the same fingerprint.

        Args:
            candidate_id: UUID of the candidate to analyze
            context_before_seconds: Seconds of context before candidate
            context_after_seconds: Seconds of context after candidate

        Returns:
            EditorialSuitabilityAnalysis (may be pending, processing, or completed)

        Raises:
            CandidateNotReadyError: If candidate is a duplicate or not selected
        """
        # Check if candidate exists and is ready
        result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotReadyError(f"Candidate {candidate_id} not found")

        if candidate.is_duplicate:
            raise CandidateNotReadyError(
                f"Candidate {candidate_id} is marked as duplicate and cannot be analyzed"
            )

        if not candidate.selected:
            raise CandidateNotReadyError(
                f"Candidate {candidate_id} must be selected before analysis"
            )

        # Get context to obtain source_id and transcription_id for fingerprint
        context = await self.context_service.get_candidate_context(
            candidate_id=candidate_id,
            context_before_seconds=context_before_seconds,
            context_after_seconds=context_after_seconds,
        )

        # Compute fingerprint for idempotency
        prompt_hash = self.editorial_provider._get_prompt_hash() or ""
        fingerprint = self._compute_request_fingerprint(
            candidate_id=candidate_id,
            source_id=UUID(context["source_id"]),
            transcription_id=UUID(context["transcription_id"]),
            context_before=context_before_seconds,
            context_after=context_after_seconds,
            strategy_id=self.STRATEGY_ID,
            strategy_version=self.STRATEGY_VERSION,
            prompt_id=self.PROMPT_ID,
            prompt_version=self.PROMPT_VERSION,
            prompt_hash=prompt_hash,
            requested_combo=self.editorial_provider.combo,
        )

        # Check for existing analysis with same fingerprint
        existing_result = await self.session.execute(
            select(EditorialSuitabilityAnalysis).where(
                EditorialSuitabilityAnalysis.request_fingerprint == fingerprint
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            logger.info(f"Found existing analysis {existing.id} for candidate {candidate_id}")
            return existing

        # Create new analysis record (context already fetched for fingerprint)
        analysis = EditorialSuitabilityAnalysis(
            candidate_id=candidate_id,
            source_id=UUID(context["source_id"]),
            transcription_id=UUID(context["transcription_id"]),
            strategy_id=self.STRATEGY_ID,
            strategy_version=self.STRATEGY_VERSION,
            prompt_id=self.PROMPT_ID,
            prompt_version=self.PROMPT_VERSION,
            prompt_hash=prompt_hash,
            config_snapshot=json.dumps({
                "context_before_seconds": context_before_seconds,
                "context_after_seconds": context_after_seconds,
            }),
            request_fingerprint=fingerprint,
            requested_combo=self.editorial_provider.combo,
            context_before_seconds=context_before_seconds,
            context_after_seconds=context_after_seconds,
            status="pending",
            attempt_count=0,
        )

        self.session.add(analysis)
        await self.session.commit()
        await self.session.refresh(analysis)

        logger.info(f"Created analysis {analysis.id} for candidate {candidate_id}")
        return analysis

    async def execute_analysis(self, analysis_id: UUID) -> EditorialSuitabilityAnalysis:
        """
        Execute the analysis (called by Celery task).

        This method performs the actual LLM call and updates the analysis
        record with results. It handles the transaction boundary correctly
        by committing state changes before and after the LLM call.

        Args:
            analysis_id: UUID of the analysis to execute

        Returns:
            Updated EditorialSuitabilityAnalysis

        Raises:
            EditorialAnalysisError: If analysis fails
        """
        # Get analysis record
        result = await self.session.execute(
            select(EditorialSuitabilityAnalysis).where(
                EditorialSuitabilityAnalysis.id == analysis_id
            )
        )
        analysis = result.scalar_one_or_none()

        if not analysis:
            raise EditorialAnalysisError(f"Analysis {analysis_id} not found")

        if analysis.status == "completed":
            logger.info(f"Analysis {analysis_id} already completed")
            return analysis

        if analysis.status == "processing":
            logger.warning(f"Analysis {analysis_id} is already being processed")
            return analysis

        # Update status to processing
        analysis.status = "processing"
        analysis.started_at = datetime.now(UTC)
        analysis.attempt_count += 1
        await self.session.commit()

        try:
            # Get context segments
            candidate_segments, before_segments, after_segments = (
                await self.context_service.get_segments_for_analysis(
                    candidate_id=analysis.candidate_id,
                    context_before_seconds=analysis.context_before_seconds,
                    context_after_seconds=analysis.context_after_seconds,
                )
            )

            # Build context for provider
            context = CandidateContext(
                candidate_id=str(analysis.candidate_id),
                candidate_segments=candidate_segments,
                context_before_segments=before_segments,
                context_after_segments=after_segments,
            )

            # Call LLM via 9Router and get resolved model
            provider_result = await self.editorial_provider.analyze_candidate_with_model(context)
            llm_response = provider_result.response
            raw_content = provider_result.raw_content

            # Update analysis with results
            analysis.standalone_score = llm_response.standalone_score
            analysis.context_dependency = llm_response.context_dependency
            analysis.hook_strength = llm_response.hook_strength
            analysis.payoff_strength = llm_response.payoff_strength
            analysis.ending_completeness = llm_response.ending_completeness
            analysis.reference_dependency_level = llm_response.reference_dependency_level
            analysis.reference_dependency_examples = {"examples": llm_response.reference_dependency_examples}
            analysis.recommended_strategy = llm_response.recommended_strategy
            analysis.recommended_start_segment_id = llm_response.recommended_start_segment_id
            analysis.recommended_end_segment_id = llm_response.recommended_end_segment_id
            analysis.analysis_summary = llm_response.analysis_summary
            analysis.raw_llm_response = raw_content
            # Persist actual physical model from 9Router, never fallback to combo alias
            if not provider_result.resolved_model:
                raise EditorialAnalysisError(
                    f"9Router did not return resolved_model for analysis {analysis_id}"
                )
            analysis.resolved_model = provider_result.resolved_model
            analysis.status = "completed"
            analysis.completed_at = datetime.now(UTC)

            await self.session.commit()
            await self.session.refresh(analysis)

            logger.info(f"Analysis {analysis_id} completed successfully")
            return analysis

        except NineRouterEditorialError as e:
            logger.error(f"Analysis {analysis_id} failed: {e}")
            analysis.status = "failed"
            analysis.error_message = str(e)
            analysis.completed_at = datetime.now(UTC)
            await self.session.commit()
            raise EditorialAnalysisError(f"Analysis failed: {e}") from e

        except Exception as e:
            logger.exception(f"Unexpected error in analysis {analysis_id}")
            analysis.status = "failed"
            analysis.error_message = str(e)
            analysis.completed_at = datetime.now(UTC)
            await self.session.commit()
            raise EditorialAnalysisError(f"Unexpected error: {e}") from e

    async def get_analysis_by_candidate(
        self, candidate_id: UUID
    ) -> EditorialSuitabilityAnalysis | None:
        """Get the most recent analysis for a candidate."""
        result = await self.session.execute(
            select(EditorialSuitabilityAnalysis)
            .where(EditorialSuitabilityAnalysis.candidate_id == candidate_id)
            .order_by(EditorialSuitabilityAnalysis.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()


__all__ = [
    "EditorialAnalysisService",
    "EditorialAnalysisError",
    "AnalysisAlreadyExistsError",
    "CandidateNotReadyError",
]
