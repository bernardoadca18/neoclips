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

from app.core.database import get_session
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
from app.services.candidate_selection_service import (
    CandidateSelectionService,
    CandidateNotFoundError as SelectionCandidateNotFoundError,
    DuplicateSelectionError,
    RunNotTerminalError,
    SelectionError,
)
from app.services.candidate_shortlist_service import (
    CandidateShortlistService,
    RunNotFoundError as ShortlistRunNotFoundError,
    RunNotTerminalError as ShortlistRunNotTerminalError,
)
from app.services.editorial_analysis_service import (
    EditorialAnalysisService,
    EditorialAnalysisError,
    CandidateNotReadyError,
)
from app.services.editorial_plan_service import (
    EditorialPlanService,
    PlanError,
    CandidateNotFoundError as PlanCandidateNotFoundError,
    AnalysisNotFoundError,
    PlanAlreadyExistsError,
    InvalidStrategyError,
)
from app.services.candidate_context_service import CandidateContextService
from app.clients.media_indexer_client import MediaIndexerClient

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
    service = EditorialPlanService(session)

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
) -> Any:
    """
    Get the editorial plan for a candidate.

    Raises:
        404: No plan found for candidate
    """
    service = EditorialPlanService(session)

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
) -> list[Any]:
    """List all editorial plans for a workflow."""
    service = EditorialPlanService(session)
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
) -> Any:
    """
    Update an editorial plan.

    Raises:
        404: Plan not found
        400: Invalid status or other validation error
    """
    service = EditorialPlanService(session)

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
