"""API endpoints for editorial operations (Stage 4).

Provides endpoints for:
- Candidate shortlist retrieval
- Candidate selection management
- Editorial suitability analysis
- Short editorial plan management
"""

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient, get_media_indexer_client
from app.core.database import get_session
from app.schemas.clip_composition import (
    ClipCompositionCreate,
    ClipCompositionRead,
    ClipCompositionUpdate,
)
from app.schemas.editorial import (
    CandidateSelectionRequest,
    CandidateSelectionResponse,
    CandidateShortlistResponse,
    EditorialSuitabilityAnalysisCreate,
    EditorialSuitabilityAnalysisRead,
    ShortEditorialPlanCreate,
    ShortEditorialPlanRead,
    ShortEditorialPlanUpdate,
)
from app.services.candidate_context_service import CandidateContextService
from app.services.candidate_selection_service import (
    CandidateNotFoundError as SelectionCandidateNotFoundError,
)
from app.services.candidate_selection_service import (
    CandidateSelectionService,
    DuplicateSelectionError,
    RunNotTerminalError,
    SelectionError,
)
from app.services.candidate_shortlist_service import (
    CandidateShortlistService,
)
from app.services.candidate_shortlist_service import (
    RunNotFoundError as ShortlistRunNotFoundError,
)
from app.services.candidate_shortlist_service import (
    RunNotTerminalError as ShortlistRunNotTerminalError,
)
from app.services.clip_composition_service import (
    ClipCompositionService,
    CompositionError,
    PlanNotReadyError,
    UnsupportedStrategyError,
)
from app.services.clip_composition_service import (
    PlanNotFoundError as CompositionPlanNotFoundError,
)
from app.services.editorial_analysis_service import (
    CandidateNotReadyError,
    EditorialAnalysisError,
    EditorialAnalysisService,
)
from app.services.editorial_plan_service import (
    AnalysisNotFoundError,
    EditorialPlanService,
    InvalidStrategyError,
    PlanAlreadyExistsError,
    PlanError,
)
from app.services.editorial_plan_service import (
    CandidateNotFoundError as PlanCandidateNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1", tags=["editorial"])


# --- Candidate Shortlist Endpoints ---


@router.get(
    "/runs/{run_id}/candidates/shortlist",
    response_model=CandidateShortlistResponse,
    summary="Get candidate shortlist for a discovery run",
    description="Returns an ordered, bounded view of the best candidates from a discovery run, suitable for editorial review.",
)
async def get_candidate_shortlist(
    run_id: UUID,
    limit: int = Query(50, ge=1, le=200, description="Maximum candidates to return"),
    include_duplicates: bool = Query(False, description="Include duplicate candidates"),
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Get the candidate shortlist for a discovery run.

    Returns candidates ordered by score_v1 descending, with metadata
    about whether each candidate has analysis or plan.

    Raises:
        404: Run not found
        400: Run not in terminal state
    """
    service = CandidateShortlistService(session)

    try:
        return await service.get_shortlist(
            run_id=run_id,
            limit=limit,
            include_duplicates=include_duplicates,
        )
    except ShortlistRunNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ShortlistRunNotTerminalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/runs/{run_id}/candidates/selected",
    response_model=list[CandidateSelectionResponse],
    summary="Get selected candidates for a run",
    description="Returns all candidates that have been selected for editorial processing.",
)
async def get_selected_candidates(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """Get all selected candidates for a run, ordered by selection_rank."""
    service = CandidateShortlistService(session)
    return await service.get_selected_candidates(run_id)


# --- Candidate Selection Endpoints ---


@router.post(
    "/candidates/{candidate_id}/select",
    response_model=CandidateSelectionResponse,
    summary="Select a candidate",
    description="Mark a candidate as selected for editorial processing. Only allowed after discovery completes.",
)
async def select_candidate(
    candidate_id: UUID,
    request: CandidateSelectionRequest,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Select a candidate for editorial processing.

    Validates:
    - Candidate exists
    - Candidate is not marked as duplicate
    - Run is in terminal state (completed, completed_with_errors, failed)

    Raises:
        404: Candidate not found
        400: Candidate is duplicate or run not terminal
    """
    service = CandidateSelectionService(session)

    try:
        candidate = await service.select_candidate(
            candidate_id=candidate_id,
            selection_rank=request.selection_rank,
        )

        return {
            "candidate_id": str(candidate_id),
            "selected": candidate.selected,
            "selection_rank": candidate.selection_rank,
            "message": f"Candidate {candidate_id} selected successfully",
        }
    except SelectionCandidateNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except DuplicateSelectionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except RunNotTerminalError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except SelectionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.delete(
    "/candidates/{candidate_id}/select",
    response_model=CandidateSelectionResponse,
    summary="Unselect a candidate",
    description="Remove selection from a candidate.",
)
async def unselect_candidate(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Unselect a candidate.

    Raises:
        404: Candidate not found
    """
    service = CandidateSelectionService(session)

    try:
        candidate = await service.unselect_candidate(candidate_id=candidate_id)

        return {
            "candidate_id": str(candidate_id),
            "selected": candidate.selected,
            "selection_rank": candidate.selection_rank,
            "message": f"Candidate {candidate_id} unselected successfully",
        }
    except SelectionCandidateNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


# --- Editorial Analysis Endpoints ---


@router.post(
    "/candidates/{candidate_id}/analyze",
    response_model=EditorialSuitabilityAnalysisRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger editorial suitability analysis",
    description="Start or retrieve an editorial suitability analysis for a candidate. Returns existing analysis if one exists.",
)
async def trigger_editorial_analysis(
    candidate_id: UUID,
    request: EditorialSuitabilityAnalysisCreate | None = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Trigger editorial suitability analysis for a candidate.

    This endpoint is idempotent - if an analysis already exists with the
    same fingerprint, it returns the existing analysis.

    The actual LLM call is handled asynchronously by a Celery task.

    Raises:
        404: Candidate not found
        400: Candidate is marked as duplicate
    """
    # Get context service dependencies
    from app.core.config import settings
    media_indexer_client = MediaIndexerClient(
        base_url=settings.media_indexer_base_url,
        timeout_seconds=settings.media_indexer_timeout_seconds,
    )
    context_service = CandidateContextService(
        session=session,
        media_indexer_client=media_indexer_client,
    )

    service = EditorialAnalysisService(
        session=session,
        context_service=context_service,
    )

    # Get context bounds from request or use defaults
    context_before = request.context_before_seconds if request else 45.0
    context_after = request.context_after_seconds if request else 40.0

    try:
        analysis = await service.get_or_create_analysis(
            candidate_id=candidate_id,
            context_before_seconds=context_before,
            context_after_seconds=context_after,
        )

        # Dispatch Celery task if analysis is pending
        if analysis.status == "pending":
            from app.tasks.editorial_tasks import execute_editorial_analysis
            execute_editorial_analysis.delay(str(analysis.id))
            logger.info(f"Dispatched analysis task for analysis {analysis.id}")

        return analysis

    except CandidateNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except EditorialAnalysisError as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e),
        )


@router.get(
    "/candidates/{candidate_id}/analysis",
    response_model=EditorialSuitabilityAnalysisRead,
    summary="Get editorial analysis for a candidate",
    description="Returns the most recent editorial suitability analysis for a candidate.",
)
async def get_editorial_analysis(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Get the most recent editorial analysis for a candidate.

    Raises:
        404: No analysis found for candidate
    """
    from app.core.config import settings
    media_indexer_client = MediaIndexerClient(
        base_url=settings.media_indexer_base_url,
        timeout_seconds=settings.media_indexer_timeout_seconds,
    )
    context_service = CandidateContextService(
        session=session,
        media_indexer_client=media_indexer_client,
    )

    service = EditorialAnalysisService(
        session=session,
        context_service=context_service,
    )

    analysis = await service.get_analysis_by_candidate(candidate_id)

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No analysis found for candidate {candidate_id}",
        )

    return analysis


@router.get(
    "/analyses/{analysis_id}",
    response_model=EditorialSuitabilityAnalysisRead,
    summary="Get an editorial analysis by ID",
)
async def get_analysis_by_id(
    analysis_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Get an editorial analysis by ID.

    Raises:
        404: Analysis not found
    """
    from sqlalchemy import select

    from app.models.entities import EditorialSuitabilityAnalysis

    result = await session.execute(
        select(EditorialSuitabilityAnalysis).where(
            EditorialSuitabilityAnalysis.id == analysis_id
        )
    )
    analysis = result.scalar_one_or_none()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Analysis {analysis_id} not found",
        )

    return analysis


# --- Editorial Plan Endpoints ---


@router.post(
    "/candidates/{candidate_id}/plan",
    response_model=ShortEditorialPlanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an editorial plan for a candidate",
    description="Create a Short Editorial Plan from analysis or manual input.",
)
async def create_editorial_plan(
    candidate_id: UUID,
    request: ShortEditorialPlanCreate,
    session: AsyncSession = Depends(get_session),
    media_indexer: MediaIndexerClient = Depends(get_media_indexer_client),
) -> Any:
    """
    Create an editorial plan for a candidate.

    Two modes:
    1. From analysis: Provide analysis_id, uses model recommendation
    2. Manual: Provide strategy and boundaries directly (human override)

    Raises:
        404: Candidate or analysis not found
        400: Invalid strategy or plan already exists
        409: Plan already exists for candidate
    """
    service = EditorialPlanService(session, media_indexer)

    try:
        if request.analysis_id:
            # Create from analysis
            plan = await service.create_plan_from_analysis(
                analysis_id=request.analysis_id,
                decision_source=request.decision_source,
            )
        else:
            # Create manual plan
            plan = await service.create_manual_plan(
                candidate_id=candidate_id,
                strategy=request.strategy,
                source_start_seconds=request.source_start_seconds,
                source_end_seconds=request.source_end_seconds,
                source_start_segment_id=request.source_start_segment_id,
                source_end_segment_id=request.source_end_segment_id,
            )

        return plan

    except PlanCandidateNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except AnalysisNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PlanAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )
    except InvalidStrategyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except PlanError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/candidates/{candidate_id}/plan",
    response_model=ShortEditorialPlanRead,
    summary="Get editorial plan for a candidate",
    description="Returns the editorial plan for a candidate if one exists.",
)
async def get_candidate_plan(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
    media_indexer: MediaIndexerClient = Depends(get_media_indexer_client),
) -> Any:
    """
    Get the editorial plan for a candidate.

    Raises:
        404: No plan found for candidate
    """
    service = EditorialPlanService(session, media_indexer)

    plan = await service.get_plan_by_candidate(candidate_id)

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No plan found for candidate {candidate_id}",
        )

    return plan


@router.get(
    "/workflows/{workflow_id}/plans",
    response_model=list[ShortEditorialPlanRead],
    summary="List editorial plans for a workflow",
    description="Returns all editorial plans for a workflow, ordered by creation date descending.",
)
async def list_workflow_plans(
    workflow_id: UUID,
    session: AsyncSession = Depends(get_session),
    media_indexer: MediaIndexerClient = Depends(get_media_indexer_client),
) -> list[Any]:
    """List all editorial plans for a workflow."""
    service = EditorialPlanService(session, media_indexer)
    return await service.get_plans_by_workflow(workflow_id)


@router.patch(
    "/plans/{plan_id}",
    response_model=ShortEditorialPlanRead,
    summary="Update an editorial plan",
    description="Update plan status or other fields.",
)
async def update_editorial_plan(
    plan_id: UUID,
    request: ShortEditorialPlanUpdate,
    session: AsyncSession = Depends(get_session),
    media_indexer: MediaIndexerClient = Depends(get_media_indexer_client),
) -> Any:
    """
    Update an editorial plan.

    Raises:
        404: Plan not found
        400: Invalid status or other validation error
    """
    service = EditorialPlanService(session, media_indexer)

    try:
        # For now, only support status updates
        if request.status:
            plan = await service.update_plan_status(
                plan_id=plan_id,
                status=request.status,
            )
            return plan
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="At least one field must be provided for update",
            )
    except PlanError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/plans/{plan_id}",
    response_model=ShortEditorialPlanRead,
    summary="Get an editorial plan by ID",
)
async def get_plan_by_id(
    plan_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Get an editorial plan by ID.

    Raises:
        404: Plan not found
    """
    from sqlalchemy import select

    from app.models.entities import ShortEditorialPlan

    result = await session.execute(
        select(ShortEditorialPlan).where(ShortEditorialPlan.id == plan_id)
    )
    plan = result.scalar_one_or_none()

    if not plan:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Plan {plan_id} not found",
        )

    return plan


# --- Clip Composition Endpoints (Stage 5) ---


@router.post(
    "/plans/{plan_id}/composition",
    response_model=ClipCompositionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a clip composition from a plan",
    description="Materialize an editorial plan into a clip composition ready for rendering.",
)
async def create_clip_composition(
    plan_id: UUID,
    request: ClipCompositionCreate | None = None,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Create a clip composition from an editorial plan.

    The plan must be in 'ready' status. Supported strategies:
    - USE_DIRECTLY: Use source boundaries as-is
    - TRIM: Trim to specified boundaries
    - ADD_CONTEXT: Include context before/after

    REAUTHOR is not yet implemented.
    REJECT is invalid for composition.

    Raises:
        404: Plan not found
        400: Plan not ready, unsupported strategy, or composition already exists
    """
    service = ClipCompositionService(session)

    try:
        composition = await service.create_composition_from_plan(
            plan_id=plan_id,
            render_profile=request.render_profile if request else "vertical_short_v1",
            audio_mode=request.audio_mode if request else "original",
            caption_mode=request.caption_mode if request else "none",
        )
        return composition

    except CompositionPlanNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except PlanNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except UnsupportedStrategyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except CompositionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/plans/{plan_id}/composition",
    response_model=ClipCompositionRead,
    summary="Get composition for a plan",
    description="Returns the clip composition for a plan if one exists.",
)
async def get_plan_composition(
    plan_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Get the clip composition for a plan.

    Raises:
        404: No composition found for plan
    """
    service = ClipCompositionService(session)

    composition = await service.get_composition_by_plan(plan_id)

    if not composition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No composition found for plan {plan_id}",
        )

    return composition


@router.get(
    "/workflows/{workflow_id}/compositions",
    response_model=list[ClipCompositionRead],
    summary="List compositions for a workflow",
    description="Returns all clip compositions for a workflow, ordered by creation date descending.",
)
async def list_workflow_compositions(
    workflow_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[Any]:
    """List all clip compositions for a workflow."""
    service = ClipCompositionService(session)
    return await service.get_compositions_by_workflow(workflow_id)


@router.patch(
    "/compositions/{composition_id}",
    response_model=ClipCompositionRead,
    summary="Update a clip composition",
    description="Update composition status or render outputs.",
)
async def update_clip_composition(
    composition_id: UUID,
    request: ClipCompositionUpdate,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Update a clip composition.

    Typically used by rendering pipeline to update status and outputs.

    Raises:
        404: Composition not found
        400: Invalid status
    """
    service = ClipCompositionService(session)

    try:
        composition = await service.update_status(
            composition_id=composition_id,
            status=request.status,
            render_job_id=request.render_job_id,
            output_media_id=request.output_media_id,
        )
        return composition

    except CompositionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get(
    "/compositions/{composition_id}",
    response_model=ClipCompositionRead,
    summary="Get a clip composition by ID",
)
async def get_composition_by_id(
    composition_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> Any:
    """
    Get a clip composition by ID.

    Raises:
        404: Composition not found
    """
    from sqlalchemy import select

    from app.models.entities import ClipComposition

    result = await session.execute(
        select(ClipComposition).where(ClipComposition.id == composition_id)
    )
    composition = result.scalar_one_or_none()

    if not composition:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Composition {composition_id} not found",
        )

    return composition
