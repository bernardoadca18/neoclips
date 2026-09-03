"""Service for managing Short Editorial Plans.

Handles the creation, update, and lifecycle of ShortEditorialPlan entities.
Plans capture the editorial decision and boundaries for producing a Short
from a ClipCandidate.
"""

import hashlib
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient
from app.models.entities import (
    ClipCandidate,
    ClipWorkflow,
    EditorialSuitabilityAnalysis,
    ShortEditorialPlan,
)
from app.services.candidate_canonicalizer import CandidateCanonicalizer

logger = logging.getLogger(__name__)


class PlanError(Exception):
    """Base error for editorial plan service."""

    pass


class CandidateNotFoundError(PlanError):
    """Raised when candidate is not found."""

    pass


class AnalysisNotFoundError(PlanError):
    """Raised when analysis is not found."""

    pass


class PlanAlreadyExistsError(PlanError):
    """Raised when plan already exists for candidate."""

    pass


class InvalidStrategyError(PlanError):
    """Raised when strategy is invalid for the operation."""

    pass


class CanonicalizationError(PlanError):
    """Raised when segment ID canonicalization fails."""

    pass


class EditorialPlanService:
    """
    Service for managing Short Editorial Plans.

    Handles:
    - Plan creation from analysis or manual input
    - Plan fingerprint for idempotency
    - Human override tracking (decision_source)
    - Plan status transitions
    """

    PLAN_VERSION = "1.0.0"

    VALID_STRATEGIES = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT", "REAUTHOR", "REJECT"}
    VALID_DECISION_SOURCES = {"model_recommendation", "human_override"}
    VALID_STATUSES = {"draft", "ready", "rejected", "invalidated"}

    def __init__(
        self, session: AsyncSession, media_indexer_client: MediaIndexerClient
    ) -> None:
        self.session = session
        self.media_indexer_client = media_indexer_client

    def _compute_fingerprint(
        self,
        candidate_id: UUID,
        strategy: str,
        start_seconds: float,
        end_seconds: float,
    ) -> str:
        """Compute SHA-256 fingerprint for plan idempotency."""
        data = f"{candidate_id}:{strategy}:{start_seconds}:{end_seconds}"
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    async def _resolve_segment_ids_to_timestamps(
        self,
        transcription_id: UUID,
        candidate_start_seconds: float,
        candidate_end_seconds: float,
        start_segment_id: UUID | None,
        end_segment_id: UUID | None,
    ) -> tuple[float, float]:
        """
        Resolve segment IDs to canonical timestamps via Media Indexer.

        Uses bounded requests to fetch only the segments within the candidate
        time range, avoiding the performance cost of loading entire transcripts.

        Args:
            transcription_id: ID of the transcription
            candidate_start_seconds: Candidate start time for bounded fetch
            candidate_end_seconds: Candidate end time for bounded fetch
            start_segment_id: Start segment ID to resolve
            end_segment_id: End segment ID to resolve

        Returns:
            Tuple of (start_seconds, end_seconds)

        Raises:
            CanonicalizationError: If segment IDs cannot be resolved or are invalid
        """
        if not start_segment_id or not end_segment_id:
            raise CanonicalizationError(
                "Segment IDs required for TRIM/ADD_CONTEXT strategies"
            )

        # Fetch only segments within candidate time range (bounded request)
        segments = await self.media_indexer_client.get_transcript_segments_by_time(
            transcription_id=transcription_id,
            start_seconds=candidate_start_seconds,
            end_seconds=candidate_end_seconds,
        )

        # Create canonicalizer and resolve
        canonicalizer = CandidateCanonicalizer(segments)
        start_segment = canonicalizer.get_segment_by_id(start_segment_id)
        end_segment = canonicalizer.get_segment_by_id(end_segment_id)

        if not start_segment:
            raise CanonicalizationError(
                f"Start segment {start_segment_id} not found in transcript range "
                f"[{candidate_start_seconds}s, {candidate_end_seconds}s]"
            )

        if not end_segment:
            raise CanonicalizationError(
                f"End segment {end_segment_id} not found in transcript range "
                f"[{candidate_start_seconds}s, {candidate_end_seconds}s]"
            )

        # Validate segment order
        if start_segment.start_seconds > end_segment.end_seconds:
            raise CanonicalizationError(
                f"Invalid segment order: start ({start_segment.start_seconds}s) "
                f"after end ({end_segment.end_seconds}s)"
            )

        return start_segment.start_seconds, end_segment.end_seconds

    async def create_plan_from_analysis(
        self,
        analysis_id: UUID,
        decision_source: str = "model_recommendation",
    ) -> ShortEditorialPlan:
        """
        Create an editorial plan from an analysis result.

        Uses the analysis's recommended strategy and boundaries.

        Args:
            analysis_id: UUID of the completed analysis
            decision_source: "model_recommendation" or "human_override"

        Returns:
            Created ShortEditorialPlan

        Raises:
            AnalysisNotFoundError: If analysis doesn't exist or isn't completed
            PlanAlreadyExistsError: If plan already exists for the candidate
        """
        # Get analysis
        result = await self.session.execute(
            select(EditorialSuitabilityAnalysis).where(
                EditorialSuitabilityAnalysis.id == analysis_id
            )
        )
        analysis = result.scalar_one_or_none()

        if not analysis:
            raise AnalysisNotFoundError(f"Analysis {analysis_id} not found")

        if analysis.status != "completed":
            raise PlanError(f"Analysis {analysis_id} is not completed (status: {analysis.status})")

        if not analysis.recommended_strategy:
            raise PlanError(f"Analysis {analysis_id} has no recommended strategy")

        # Get candidate for lineage
        candidate_result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == analysis.candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {analysis.candidate_id} not found")

        # Get workflow for lineage
        from app.models.entities import DiscoveryRun
        run_result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == candidate.run_id)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            raise PlanError(f"Run {candidate.run_id} not found")

        workflow_result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == run.workflow_id)
        )
        workflow = workflow_result.scalar_one_or_none()

        if not workflow:
            raise PlanError(f"Workflow {run.workflow_id} not found")

        # Check for existing plan
        existing_result = await self.session.execute(
            select(ShortEditorialPlan).where(
                ShortEditorialPlan.candidate_id == candidate.id
            )
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            raise PlanAlreadyExistsError(
                f"Plan already exists for candidate {candidate.id}"
            )

        # Resolve segment IDs to canonical timestamps for TRIM/ADD_CONTEXT
        # NOTE: USE_DIRECTLY and REJECT use candidate boundaries as-is
        # REAUTHOR is not yet implemented
        resolved_start = candidate.canonical_start_seconds
        resolved_end = candidate.canonical_end_seconds

        if analysis.recommended_strategy in ("TRIM", "ADD_CONTEXT"):
            # This will raise CanonicalizationError if segments cannot be resolved
            # We do NOT silently fallback - explicit failure is required
            resolved_start, resolved_end = await self._resolve_segment_ids_to_timestamps(
                transcription_id=analysis.transcription_id,
                candidate_start_seconds=candidate.canonical_start_seconds,
                candidate_end_seconds=candidate.canonical_end_seconds,
                start_segment_id=analysis.recommended_start_segment_id,
                end_segment_id=analysis.recommended_end_segment_id,
            )

        # Compute fingerprint with resolved boundaries
        fingerprint = self._compute_fingerprint(
            candidate_id=candidate.id,
            strategy=analysis.recommended_strategy,
            start_seconds=resolved_start,
            end_seconds=resolved_end,
        )

        # Create plan
        duration = resolved_end - resolved_start
        plan = ShortEditorialPlan(
            workflow_id=workflow.id,
            source_id=workflow.source_id,
            candidate_id=candidate.id,
            analysis_id=analysis_id,
            strategy=analysis.recommended_strategy,
            decision_source=decision_source,
            source_start_segment_id=analysis.recommended_start_segment_id,
            source_end_segment_id=analysis.recommended_end_segment_id,
            source_start_seconds=resolved_start,
            source_end_seconds=resolved_end,
            duration_seconds=duration,
            recommended_strategy=analysis.recommended_strategy,
            recommended_start_segment_id=analysis.recommended_start_segment_id,
            recommended_end_segment_id=analysis.recommended_end_segment_id,
            status="draft",
            plan_version=self.PLAN_VERSION,
            config_snapshot=analysis.config_snapshot,
            fingerprint=fingerprint,
        )

        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)

        logger.info(f"Created plan {plan.id} from analysis {analysis_id}")
        return plan

    async def create_manual_plan(
        self,
        candidate_id: UUID,
        strategy: str,
        source_start_seconds: float,
        source_end_seconds: float,
        source_start_segment_id: UUID | None = None,
        source_end_segment_id: UUID | None = None,
        rejection_reason: str | None = None,
    ) -> ShortEditorialPlan:
        """
        Create an editorial plan manually (human override).

        Args:
            candidate_id: UUID of the candidate
            strategy: Editorial strategy
            source_start_seconds: Start boundary in seconds
            source_end_seconds: End boundary in seconds
            source_start_segment_id: Optional start segment ID
            source_end_segment_id: Optional end segment ID
            rejection_reason: Required if strategy is REJECT

        Returns:
            Created ShortEditorialPlan

        Raises:
            CandidateNotFoundError: If candidate doesn't exist
            InvalidStrategyError: If strategy is invalid
        """
        if strategy not in self.VALID_STRATEGIES:
            raise InvalidStrategyError(f"Invalid strategy: {strategy}")

        if strategy == "REJECT" and not rejection_reason:
            raise PlanError("rejection_reason is required for REJECT strategy")

        # Get candidate and lineage
        candidate_result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            raise CandidateNotFoundError(f"Candidate {candidate_id} not found")

        from app.models.entities import DiscoveryRun
        run_result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == candidate.run_id)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            raise PlanError(f"Run {candidate.run_id} not found")

        workflow_result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == run.workflow_id)
        )
        workflow = workflow_result.scalar_one_or_none()

        if not workflow:
            raise PlanError(f"Workflow {run.workflow_id} not found")

        # Compute fingerprint
        fingerprint = self._compute_fingerprint(
            candidate_id=candidate_id,
            strategy=strategy,
            start_seconds=source_start_seconds,
            end_seconds=source_end_seconds,
        )

        duration = source_end_seconds - source_start_seconds

        plan = ShortEditorialPlan(
            workflow_id=workflow.id,
            source_id=workflow.source_id,
            candidate_id=candidate_id,
            analysis_id=None,
            strategy=strategy,
            decision_source="human_override",
            source_start_segment_id=source_start_segment_id,
            source_end_segment_id=source_end_segment_id,
            source_start_seconds=source_start_seconds,
            source_end_seconds=source_end_seconds,
            duration_seconds=duration,
            rejection_reason=rejection_reason,
            status="draft",
            plan_version=self.PLAN_VERSION,
            fingerprint=fingerprint,
        )

        self.session.add(plan)
        await self.session.commit()
        await self.session.refresh(plan)

        logger.info(f"Created manual plan {plan.id} for candidate {candidate_id}")
        return plan

    async def update_plan_status(
        self,
        plan_id: UUID,
        status: str,
    ) -> ShortEditorialPlan:
        """
        Update the status of a plan.

        Args:
            plan_id: UUID of the plan
            status: New status (draft, ready, rejected, invalidated)

        Returns:
            Updated ShortEditorialPlan

        Raises:
            PlanError: If plan not found or status invalid
        """
        if status not in self.VALID_STATUSES:
            raise PlanError(f"Invalid status: {status}")

        result = await self.session.execute(
            select(ShortEditorialPlan).where(ShortEditorialPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()

        if not plan:
            raise PlanError(f"Plan {plan_id} not found")

        plan.status = status
        await self.session.commit()
        await self.session.refresh(plan)

        logger.info(f"Plan {plan_id} status updated to {status}")
        return plan

    async def get_plan_by_candidate(
        self, candidate_id: UUID
    ) -> ShortEditorialPlan | None:
        """Get the plan for a candidate."""
        result = await self.session.execute(
            select(ShortEditorialPlan).where(
                ShortEditorialPlan.candidate_id == candidate_id
            )
        )
        return result.scalar_one_or_none()

    async def get_plans_by_workflow(
        self, workflow_id: UUID
    ) -> list[ShortEditorialPlan]:
        """Get all plans for a workflow."""
        result = await self.session.execute(
            select(ShortEditorialPlan)
            .where(ShortEditorialPlan.workflow_id == workflow_id)
            .order_by(ShortEditorialPlan.created_at.desc())
        )
        return list(result.scalars().all())


__all__ = [
    "EditorialPlanService",
    "PlanError",
    "CandidateNotFoundError",
    "AnalysisNotFoundError",
    "PlanAlreadyExistsError",
    "InvalidStrategyError",
    "CanonicalizationError",
]
