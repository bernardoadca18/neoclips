"""Service for managing Clip Compositions (Stage 5).

Handles the creation and lifecycle of ClipComposition entities,
bridging editorial plans (Stage 4) and rendering (Stage 6).
"""

import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    ClipComposition,
    ShortEditorialPlan,
)

logger = logging.getLogger(__name__)


class CompositionError(Exception):
    """Base error for composition service."""

    pass


class PlanNotFoundError(CompositionError):
    """Raised when plan is not found."""

    pass


class PlanNotReadyError(CompositionError):
    """Raised when plan is not ready for composition."""

    pass


class CompositionAlreadyExistsError(CompositionError):
    """Raised when composition already exists for plan."""

    pass


class UnsupportedStrategyError(CompositionError):
    """Raised when strategy is not supported."""

    pass


class ClipCompositionService:
    """
    Service for managing Clip Compositions.

    Handles:
    - Composition creation from editorial plans
    - Strategy validation (USE_DIRECTLY, TRIM, ADD_CONTEXT only)
    - Fingerprint for idempotency
    - Status transitions
    """

    RENDER_PROFILE_VERSION = "vertical_short_v1"

    SUPPORTED_STRATEGIES = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT"}
    UNSUPPORTED_STRATEGIES = {"REAUTHOR"}  # Not yet implemented
    REJECTED_STRATEGIES = {"REJECT"}  # Invalid for composition

    VALID_STATUSES = {"pending", "validating", "ready", "rendering", "completed", "failed"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _compute_fingerprint(
        self,
        plan_id: UUID,
        strategy: str,
        source_start_seconds: float,
        source_end_seconds: float,
        render_profile: str,
        audio_mode: str,
        caption_mode: str,
    ) -> str:
        """Compute SHA-256 fingerprint for composition idempotency.

        The fingerprint includes all parameters that affect the rendered output:
        - plan_id: the editorial plan being materialized
        - strategy: how to process the source
        - boundaries: source start/end times
        - render_profile: versioned rendering configuration
        - audio_mode: audio handling mode
        - caption_mode: caption handling mode
        """
        data = json.dumps({
            "plan_id": str(plan_id),
            "strategy": strategy,
            "source_start_seconds": source_start_seconds,
            "source_end_seconds": source_end_seconds,
            "render_profile": render_profile,
            "audio_mode": audio_mode,
            "caption_mode": caption_mode,
        }, sort_keys=True)
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    async def create_composition_from_analysis(
        self,
        analysis_id: UUID,
        render_profile: str = "vertical_short_v1",
        audio_mode: str = "original",
        caption_mode: str = "none",
    ) -> ClipComposition:
        """
        Create a clip composition directly from an analysis.

        This creates both the editorial plan AND the composition in one step,
        useful for automated workflows that don't require human review.

        Args:
            analysis_id: UUID of the completed editorial analysis
            render_profile: Render profile to use (default: vertical_short_v1)
            audio_mode: Audio handling mode (default: original)
            caption_mode: Caption handling mode (default: none)

        Returns:
            Created ClipComposition

        Raises:
            PlanNotFoundError: If analysis doesn't exist
            PlanNotReadyError: If analysis is not completed
            CompositionAlreadyExistsError: If composition already exists
            UnsupportedStrategyError: If strategy is REAUTHOR or REJECT
        """
        from app.services.editorial_plan_service import EditorialPlanService

        # Create plan from analysis first
        plan_service = EditorialPlanService(self.session, None)  # type: ignore
        plan = await plan_service.create_plan_from_analysis(analysis_id)

        # Transition plan to ready
        plan = await plan_service.update_plan_status(plan.id, "ready")

        # Now create composition from the plan
        return await self.create_composition_from_plan(
            plan_id=plan.id,
            render_profile=render_profile,
            audio_mode=audio_mode,
            caption_mode=caption_mode,
        )

    async def create_composition_from_plan(
        self,
        plan_id: UUID,
        render_profile: str = "vertical_short_v1",
        audio_mode: str = "original",
        caption_mode: str = "none",
    ) -> ClipComposition:
        """
        Create a clip composition from an editorial plan.

        Args:
            plan_id: UUID of the editorial plan
            render_profile: Render profile to use (default: vertical_short_v1)
            audio_mode: Audio handling mode (default: original)
            caption_mode: Caption handling mode (default: none)

        Returns:
            Created ClipComposition

        Raises:
            PlanNotFoundError: If plan doesn't exist
            PlanNotReadyError: If plan status is not "ready"
            CompositionAlreadyExistsError: If composition already exists for plan
            UnsupportedStrategyError: If strategy is REAUTHOR or REJECT
        """
        # Get plan
        result = await self.session.execute(
            select(ShortEditorialPlan).where(ShortEditorialPlan.id == plan_id)
        )
        plan = result.scalar_one_or_none()

        if not plan:
            raise PlanNotFoundError(f"Plan {plan_id} not found")

        if plan.status != "ready":
            raise PlanNotReadyError(
                f"Plan {plan_id} is not ready (status: {plan.status}). "
                "Plan must be in 'ready' status before composition."
            )

        # Validate strategy
        if plan.strategy in self.REJECTED_STRATEGIES:
            raise UnsupportedStrategyError(
                f"Strategy '{plan.strategy}' is rejected and cannot be composed"
            )

        if plan.strategy in self.UNSUPPORTED_STRATEGIES:
            raise UnsupportedStrategyError(
                f"Strategy '{plan.strategy}' is not yet implemented. "
                "Only USE_DIRECTLY, TRIM, and ADD_CONTEXT are supported."
            )

        if plan.strategy not in self.SUPPORTED_STRATEGIES:
            raise UnsupportedStrategyError(
                f"Unknown strategy '{plan.strategy}'. "
                f"Supported strategies: {self.SUPPORTED_STRATEGIES}"
            )

        # Check for existing composition
        existing_result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.plan_id == plan_id)
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            raise CompositionAlreadyExistsError(
                f"Composition already exists for plan {plan_id}"
            )

        # Compute fingerprint
        fingerprint = self._compute_fingerprint(
            plan_id=plan.id,
            strategy=plan.strategy,
            source_start_seconds=plan.source_start_seconds,
            source_end_seconds=plan.source_end_seconds,
            render_profile=render_profile,
            audio_mode=audio_mode,
            caption_mode=caption_mode,
        )

        # Create composition
        composition = ClipComposition(
            workflow_id=plan.workflow_id,
            source_id=plan.source_id,
            plan_id=plan.id,
            analysis_id=plan.analysis_id,
            source_start_seconds=plan.source_start_seconds,
            source_end_seconds=plan.source_end_seconds,
            duration_seconds=plan.duration_seconds,
            source_start_segment_id=plan.source_start_segment_id,
            source_end_segment_id=plan.source_end_segment_id,
            strategy=plan.strategy,
            render_profile=render_profile,
            composition_version=2,
            audio_mode=audio_mode,
            caption_mode=caption_mode,
            status="pending",
            fingerprint=fingerprint,
        )

        self.session.add(composition)
        await self.session.commit()
        await self.session.refresh(composition)

        logger.info(f"Created composition {composition.id} from plan {plan_id}")
        return composition

    async def update_status(
        self,
        composition_id: UUID,
        status: str,
        render_job_id: UUID | None = None,
        output_media_id: UUID | None = None,
    ) -> ClipComposition:
        """
        Update the status of a composition.

        Args:
            composition_id: UUID of the composition
            status: New status
            render_job_id: Optional render job ID (for rendering status)
            output_media_id: Optional output media ID (for completed status)

        Returns:
            Updated ClipComposition

        Raises:
            CompositionError: If composition not found or status invalid
        """
        if status not in self.VALID_STATUSES:
            raise CompositionError(f"Invalid status: {status}")

        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.id == composition_id)
        )
        composition = result.scalar_one_or_none()

        if not composition:
            raise CompositionError(f"Composition {composition_id} not found")

        composition.status = status

        if render_job_id:
            composition.render_job_id = render_job_id

        if output_media_id:
            composition.output_media_id = output_media_id

        await self.session.commit()
        await self.session.refresh(composition)

        logger.info(f"Composition {composition_id} status updated to {status}")
        return composition

    async def get_composition_by_plan(
        self, plan_id: UUID
    ) -> ClipComposition | None:
        """Get the composition for a plan."""
        result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.plan_id == plan_id)
        )
        return result.scalar_one_or_none()

    async def get_compositions_by_workflow(
        self, workflow_id: UUID
    ) -> list[ClipComposition]:
        """Get all compositions for a workflow."""
        result = await self.session.execute(
            select(ClipComposition)
            .where(ClipComposition.workflow_id == workflow_id)
            .order_by(ClipComposition.created_at.desc())
        )
        return list(result.scalars().all())


__all__ = [
    "ClipCompositionService",
    "CompositionError",
    "PlanNotFoundError",
    "PlanNotReadyError",
    "CompositionAlreadyExistsError",
    "UnsupportedStrategyError",
]
