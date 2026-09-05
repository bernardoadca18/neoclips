"""Service for managing Clip Compositions (Stage 5).

Handles the creation and lifecycle of ClipComposition entities,
bridging editorial plans (Stage 4) and rendering (Stage 6).
"""

import hashlib
import json
import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    ClipCandidate,
    ClipComposition,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    EditorialSuitabilityAnalysis,
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
    """Raised when composition already exists with same fingerprint.

    Deprecated: Use fingerprint-based lookup for idempotency.
    """

    pass


class UnsupportedStrategyError(CompositionError):
    """Raised when strategy is not supported."""

    pass


class IncompleteLineageError(CompositionError):
    """Raised when required lineage is missing."""

    pass


class LineageMismatchError(CompositionError):
    """Raised when lineage cross-entity validation fails."""

    pass


class ClipCompositionService:
    """
    Service for managing Clip Compositions.

    Handles:
    - Composition creation from editorial plans
    - Strategy validation (USE_DIRECTLY, TRIM, ADD_CONTEXT only)
    - Full lineage resolution and validation
    - Fingerprint for idempotency (computed AFTER lineage resolution)
    - Status transitions

    Invariants:
    - A 'ready' composition MUST have complete lineage
    - Fingerprint includes all material fields including provenance
    - Lineage is validated for cross-entity consistency
    """

    COMPOSITION_CONTRACT_VERSION = "clip_composition_v2"
    RENDER_PROFILE_VERSION = "vertical_short_v1"

    SUPPORTED_STRATEGIES = {"USE_DIRECTLY", "TRIM", "ADD_CONTEXT"}
    UNSUPPORTED_STRATEGIES = {"REAUTHOR"}  # Not yet implemented
    REJECTED_STRATEGIES = {"REJECT"}  # Invalid for composition

    VALID_STATUSES = {"pending", "validating", "ready", "rendering", "completed", "failed"}

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _compute_fingerprint(
        self,
        workflow_id: UUID,
        source_id: UUID,
        candidate_id: UUID,
        analysis_id: UUID | None,
        plan_id: UUID,
        media_id: UUID,
        transcription_id: UUID,
        source_sha256: str,
        source_start_seconds: float,
        source_end_seconds: float,
        strategy: str,
        render_profile: str,
        audio_mode: str,
        caption_mode: str,
        composition_contract_version: str,
    ) -> str:
        """Compute SHA-256 fingerprint for composition idempotency.

        The fingerprint includes ALL parameters that affect the composition identity:
        - Lineage: workflow, source, candidate, analysis, plan, media, transcription, sha256
        - Boundaries: source start/end times
        - Editorial: strategy
        - Render config: profile, audio_mode, caption_mode
        - Contract version: for schema evolution

        This MUST be called AFTER lineage is fully resolved and validated.
        """
        data = json.dumps({
            "composition_contract_version": composition_contract_version,
            "workflow_id": str(workflow_id),
            "source_id": str(source_id),
            "candidate_id": str(candidate_id),
            "analysis_id": str(analysis_id) if analysis_id else None,
            "plan_id": str(plan_id),
            "media_id": str(media_id),
            "transcription_id": str(transcription_id),
            "source_sha256": source_sha256,
            "source_start_seconds": source_start_seconds,
            "source_end_seconds": source_end_seconds,
            "strategy": strategy,
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

        This method resolves full lineage BEFORE creating the composition:
        1. Load plan and validate status/strategy
        2. Load ClipSource to get media_id, transcription_id, source_sha256
        3. Validate cross-entity lineage consistency
        4. Compute fingerprint AFTER lineage resolution
        5. Check idempotency by fingerprint
        6. Create composition with complete lineage

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
            UnsupportedStrategyError: If strategy is REAUTHOR or REJECT
            IncompleteLineageError: If required lineage is missing
            LineageMismatchError: If cross-entity validation fails
        """
        # Step 1: Load and validate plan
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

        # Step 2: Resolve lineage from ClipSource
        if not plan.source_id:
            raise IncompleteLineageError(
                f"Plan {plan_id} has no source_id - cannot resolve lineage"
            )

        source_result = await self.session.execute(
            select(ClipSource).where(ClipSource.id == plan.source_id)
        )
        source = source_result.scalar_one_or_none()

        if not source:
            raise IncompleteLineageError(
                f"ClipSource {plan.source_id} not found for plan {plan_id}"
            )

        # Extract lineage fields from ClipSource
        media_id = source.media_id
        transcription_id = source.transcription_id
        source_sha256 = source.source_sha256

        # Validate required lineage fields are present
        if media_id is None:
            raise IncompleteLineageError(
                f"ClipSource {source.id} has no media_id - "
                "source must be fully ingested before composition"
            )

        if transcription_id is None:
            raise IncompleteLineageError(
                f"ClipSource {source.id} has no transcription_id - "
                "transcription must be complete before composition"
            )

        if source_sha256 is None:
            raise IncompleteLineageError(
                f"ClipSource {source.id} has no source_sha256 - "
                "source must be fully ingested before composition"
            )

        # RESÍDUO 4: Validate source_sha256 format (64-char lowercase hex)
        import re
        if not re.match(r'^[a-f0-9]{64}$', source_sha256):
            raise LineageMismatchError(
                f"ClipSource {source.id} has invalid source_sha256 format - "
                f"expected 64 lowercase hex characters, got '{source_sha256}'"
            )

        # Step 3: Resolve candidate_id from analysis or plan
        candidate_id: UUID | None = None

        if plan.analysis_id:
            analysis_result = await self.session.execute(
                select(EditorialSuitabilityAnalysis).where(
                    EditorialSuitabilityAnalysis.id == plan.analysis_id
                )
            )
            analysis = analysis_result.scalar_one_or_none()

            if analysis:
                candidate_id = analysis.candidate_id

                # Cross-entity validation: analysis.candidate_id should match plan's expected
                if plan.candidate_id and analysis.candidate_id != plan.candidate_id:
                    raise LineageMismatchError(
                        f"Plan candidate_id {plan.candidate_id} does not match "
                        f"analysis candidate_id {analysis.candidate_id}"
                    )

                # RESÍDUO 2: Validate analysis.transcription_id == source.transcription_id
                if analysis.transcription_id is None:
                    raise IncompleteLineageError(
                        f"EditorialSuitabilityAnalysis {analysis.id} has no transcription_id"
                    )
                if analysis.transcription_id != transcription_id:
                    raise LineageMismatchError(
                        f"EditorialSuitabilityAnalysis transcription_id {analysis.transcription_id} "
                        f"does not match ClipSource transcription_id {transcription_id}"
                    )
            else:
                # RESÍDUO 3: If analysis_id is set but analysis not found, fail explicitly
                raise IncompleteLineageError(
                    f"ShortEditorialPlan {plan_id} references analysis_id {plan.analysis_id} "
                    "which does not exist"
                )

        # If plan has candidate_id directly, use it
        if plan.candidate_id:
            candidate_id = plan.candidate_id

        if candidate_id is None:
            raise IncompleteLineageError(
                f"Cannot resolve candidate_id for plan {plan_id} - "
                "plan has no candidate_id and analysis is missing or has no candidate_id"
            )

        # Step 3.5: Validate full lineage chain
        # Chain: ClipSource → ClipWorkflow → DiscoveryRun → ClipCandidate → Analysis → Plan
        # Load ClipWorkflow
        workflow_result = await self.session.execute(
            select(ClipWorkflow).where(ClipWorkflow.id == plan.workflow_id)
        )
        workflow = workflow_result.scalar_one_or_none()

        if not workflow:
            raise IncompleteLineageError(
                f"ClipWorkflow {plan.workflow_id} not found for plan {plan_id}"
            )

        # Cross-validate: workflow.source_id == plan.source_id
        if workflow.source_id != plan.source_id:
            raise LineageMismatchError(
                f"Workflow source_id {workflow.source_id} does not match "
                f"plan source_id {plan.source_id}"
            )

        # Load ClipCandidate
        candidate_result = await self.session.execute(
            select(ClipCandidate).where(ClipCandidate.id == candidate_id)
        )
        candidate = candidate_result.scalar_one_or_none()

        if not candidate:
            raise IncompleteLineageError(
                f"ClipCandidate {candidate_id} not found for plan {plan_id}"
            )

        # Load DiscoveryRun via candidate.run_id
        run_result = await self.session.execute(
            select(DiscoveryRun).where(DiscoveryRun.id == candidate.run_id)
        )
        run = run_result.scalar_one_or_none()

        if not run:
            raise IncompleteLineageError(
                f"DiscoveryRun {candidate.run_id} not found for candidate {candidate_id}"
            )

        # Cross-validate: run.workflow_id == workflow.id
        if run.workflow_id != workflow.id:
            raise LineageMismatchError(
                f"DiscoveryRun workflow_id {run.workflow_id} does not match "
                f"ClipWorkflow id {workflow.id}"
            )

        # Cross-validate: run.source_id == plan.source_id
        if run.source_id != plan.source_id:
            raise LineageMismatchError(
                f"DiscoveryRun source_id {run.source_id} does not match "
                f"plan source_id {plan.source_id}"
            )

        # RESÍDUO 1: Validate run.transcription_id == source.transcription_id
        if run.transcription_id is None:
            raise IncompleteLineageError(
                f"DiscoveryRun {run.id} has no transcription_id - "
                "discovery must complete transcription before composition"
            )
        if run.transcription_id != transcription_id:
            raise LineageMismatchError(
                f"DiscoveryRun transcription_id {run.transcription_id} does not match "
                f"ClipSource transcription_id {transcription_id}"
            )

        # Cross-validate: analysis lineage if present
        if plan.analysis_id and analysis:
            # analysis.candidate_id should match candidate_id
            if analysis.candidate_id != candidate_id:
                raise LineageMismatchError(
                    f"Analysis candidate_id {analysis.candidate_id} does not match "
                    f"resolved candidate_id {candidate_id}"
                )
            # analysis.source_id should match plan.source_id
            if analysis.source_id != plan.source_id:
                raise LineageMismatchError(
                    f"Analysis source_id {analysis.source_id} does not match "
                    f"plan source_id {plan.source_id}"
                )

        # Step 4: Compute fingerprint AFTER lineage resolution
        fingerprint = self._compute_fingerprint(
            workflow_id=plan.workflow_id,
            source_id=plan.source_id,
            candidate_id=candidate_id,
            analysis_id=plan.analysis_id,
            plan_id=plan.id,
            media_id=media_id,
            transcription_id=transcription_id,
            source_sha256=source_sha256,
            source_start_seconds=plan.source_start_seconds,
            source_end_seconds=plan.source_end_seconds,
            strategy=plan.strategy,
            render_profile=render_profile,
            audio_mode=audio_mode,
            caption_mode=caption_mode,
            composition_contract_version=self.COMPOSITION_CONTRACT_VERSION,
        )

        # Step 5: Check for existing composition by fingerprint (idempotency)
        existing_result = await self.session.execute(
            select(ClipComposition).where(ClipComposition.fingerprint == fingerprint)
        )
        existing = existing_result.scalar_one_or_none()

        if existing:
            logger.info(
                f"Composition already exists with fingerprint {fingerprint[:16]}..., returning existing"
            )
            return existing  # type: ignore[no-any-return]

        # Step 6: Create composition with complete lineage
        composition = ClipComposition(
            workflow_id=plan.workflow_id,
            source_id=plan.source_id,
            plan_id=plan.id,
            analysis_id=plan.analysis_id,
            # Complete lineage - no None values for ready composition
            candidate_id=candidate_id,
            media_id=media_id,
            transcription_id=transcription_id,
            source_sha256=source_sha256,
            # Timing fields
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
            status="ready",
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
        return composition  # type: ignore[no-any-return]

    async def get_compositions_by_plan(
        self, plan_id: UUID
    ) -> list[ClipComposition]:
        """Get all compositions for a plan.

        Returns all variants (different render_profile/audio_mode/caption_mode)
        for a single plan. Use this when you need to handle multiple compositions
        per plan.

        Returns:
            List of ClipComposition entities (may be empty)
        """
        result = await self.session.execute(
            select(ClipComposition)
            .where(ClipComposition.plan_id == plan_id)
            .order_by(ClipComposition.created_at.desc())
        )
        return list(result.scalars().all())

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
    "IncompleteLineageError",
    "LineageMismatchError",
]
