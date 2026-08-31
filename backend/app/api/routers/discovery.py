"""API endpoints for clip discovery (Stage 3)."""

import logging
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.entities import ClipCandidate, DiscoveryRun, DiscoveryWindow
from app.repositories.discovery_repository import (
    ClipCandidateRepository,
    DiscoveryRunRepository,
    DiscoveryWindowRepository,
)
from app.schemas.discovery import (
    ClipCandidateRead,
    ClipCandidateUpdate,
    DiscoveryRunCreate,
    DiscoveryRunRead,
    DiscoveryRunUpdate,
    DiscoveryWindowRead,
)

logger = logging.getLogger(__name__)

# Window configuration
WINDOW_DURATION_SECONDS = 300.0
WINDOW_OVERLAP_SECONDS = 60.0


router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


@router.post(
    "/workflows/{workflow_id}/discover",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_202_ACCEPTED,
    deprecated=True,
    summary="Start clip discovery for a workflow (deprecated)",
    description="DEPRECATED: Use POST /v1/workflows/{workflow_id}/discover instead. This endpoint delegates to the canonical endpoint.",
)
async def start_discovery(
    workflow_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """
    Start clip discovery for a workflow.

    DEPRECATED: This endpoint delegates to DiscoveryBootstrapService.
    Use POST /v1/workflows/{workflow_id}/discover instead.

    Returns:
        DiscoveryRun with status 'running' and window counts populated.
    """
    import logging

    from app.services.discovery_bootstrap_service import (
        DiscoveryBootstrapService,
        IdempotencyConflictError,
        SourceNotFoundError,
        SourceNotReadyError,
        TranscriptionNotFoundError,
        WorkflowNotFoundError,
    )

    logger = logging.getLogger(__name__)

    service = DiscoveryBootstrapService(session)

    try:
        result = await service.bootstrap(
            workflow_id=workflow_id,
            idempotency_key=idempotency_key,
        )
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except SourceNotReadyError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except TranscriptionNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(e),
        )
    except IdempotencyConflictError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency key already used with different configuration",
        )

    run = result.run

    # Dispatch first window task if newly created
    if result.created and result.windows:
        from app.tasks.discovery_tasks import process_window

        first_window = result.windows[0]
        process_window.delay(str(first_window.id), str(run.id))
        logger.info(
            f"Created discovery run {run.id} with {len(result.windows)} windows, "
            f"dispatched first window {first_window.id}"
        )

    return run


@router.post(
    "/runs",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
    summary="Create a discovery run (deprecated)",
    description="Use POST /workflows/{workflow_id}/discover instead.",
)
async def create_discovery_run(
    run_create: DiscoveryRunCreate,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """Create a discovery run. Deprecated - use /workflows/{workflow_id}/discover."""
    run_repository = DiscoveryRunRepository(session)

    run = DiscoveryRun(
        workflow_id=run_create.workflow_id,
        status="pending",
        profile=run_create.profile,
        total_windows=0,
        processed_windows=0,
        total_candidates=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    return await run_repository.create(run)


@router.get(
    "/runs/{run_id}",
    response_model=DiscoveryRunRead,
    summary="Get a discovery run",
)
async def get_discovery_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """Get a discovery run by ID."""
    run_repository = DiscoveryRunRepository(session)
    run = await run_repository.get_by_id(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery run {run_id} not found",
        )

    return run


@router.get(
    "/runs",
    response_model=list[DiscoveryRunRead],
    summary="List discovery runs",
)
async def list_discovery_runs(
    workflow_id: UUID | None = Query(None, description="Filter by workflow ID"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[DiscoveryRun]:
    """List discovery runs with optional filtering."""
    run_repository = DiscoveryRunRepository(session)

    if workflow_id:
        return await run_repository.get_by_workflow_id(workflow_id)

    return await run_repository.list(limit=limit, offset=offset)


@router.patch(
    "/runs/{run_id}",
    response_model=DiscoveryRunRead,
    summary="Update a discovery run",
)
async def update_discovery_run(
    run_id: UUID,
    run_update: DiscoveryRunUpdate,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """Update a discovery run."""
    run_repository = DiscoveryRunRepository(session)
    run = await run_repository.get_by_id(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery run {run_id} not found",
        )

    update_data = run_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(run, field, value)

    run.updated_at = datetime.now(UTC)
    return await run_repository.update(run)


@router.get(
    "/runs/{run_id}/windows",
    response_model=list[DiscoveryWindowRead],
    summary="List windows for a discovery run",
)
async def list_discovery_windows(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[DiscoveryWindow]:
    """List all windows for a discovery run."""
    window_repository = DiscoveryWindowRepository(session)
    return await window_repository.get_by_run_id(run_id)


@router.get(
    "/windows/{window_id}",
    response_model=DiscoveryWindowRead,
    summary="Get a discovery window",
)
async def get_discovery_window(
    window_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryWindow:
    """Get a discovery window by ID."""
    window_repository = DiscoveryWindowRepository(session)
    window = await window_repository.get_by_id(window_id)

    if not window:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery window {window_id} not found",
        )

    return window


@router.get(
    "/runs/{run_id}/candidates",
    response_model=list[ClipCandidateRead],
    summary="List candidates for a discovery run",
)
async def list_discovery_candidates(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ClipCandidate]:
    """List all candidates for a discovery run."""
    candidate_repository = ClipCandidateRepository(session)
    return await candidate_repository.get_by_run_id(run_id)


@router.get(
    "/candidates/{candidate_id}",
    response_model=ClipCandidateRead,
    summary="Get a clip candidate",
)
async def get_clip_candidate(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ClipCandidate:
    """Get a clip candidate by ID."""
    candidate_repository = ClipCandidateRepository(session)
    candidate = await candidate_repository.get_by_id(candidate_id)

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip candidate {candidate_id} not found",
        )

    return candidate


@router.patch(
    "/candidates/{candidate_id}",
    response_model=ClipCandidateRead,
    summary="Update a clip candidate",
)
async def update_clip_candidate(
    candidate_id: UUID,
    candidate_update: ClipCandidateUpdate,
    session: AsyncSession = Depends(get_session),
) -> ClipCandidate:
    """Update a clip candidate."""
    candidate_repository = ClipCandidateRepository(session)
    candidate = await candidate_repository.get_by_id(candidate_id)

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip candidate {candidate_id} not found",
        )

    update_data = candidate_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(candidate, field, value)

    candidate.updated_at = datetime.now(UTC)
    return await candidate_repository.update(candidate)
