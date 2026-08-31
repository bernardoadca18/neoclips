"""API endpoints for clip discovery (Stage 3)."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.models.entities import ClipCandidate, ClipWorkflow, DiscoveryRun, DiscoveryWindow
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

router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


@router.post(
    "/runs",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a discovery run",
    description="Create a new clip discovery run for a workflow.",
)
async def create_discovery_run(
    data: DiscoveryRunCreate,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """Create a new discovery run."""
    # Verify workflow exists
    result = await session.execute(
        select(ClipWorkflow).where(ClipWorkflow.id == data.workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {data.workflow_id} not found",
        )

    # Create run
    run = DiscoveryRun(
        workflow_id=data.workflow_id,
        status="pending",
        profile=data.profile,
        total_windows=0,
        processed_windows=0,
        total_candidates=0,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    return run


@router.get(
    "/runs/{run_id}",
    response_model=DiscoveryRunRead,
    summary="Get a discovery run",
    description="Get details of a specific discovery run.",
)
async def get_discovery_run(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """Get a discovery run by ID."""
    repository = DiscoveryRunRepository(session)
    run = await repository.get(run_id)

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
    description="List discovery runs, optionally filtered by workflow.",
)
async def list_discovery_runs(
    workflow_id: UUID | None = Query(None, description="Filter by workflow ID"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[DiscoveryRun]:
    """List discovery runs."""
    repository = DiscoveryRunRepository(session)

    if workflow_id:
        return await repository.get_by_workflow_id(workflow_id)

    return await repository.get_all(limit=limit, offset=offset)


@router.patch(
    "/runs/{run_id}",
    response_model=DiscoveryRunRead,
    summary="Update a discovery run",
    description="Update discovery run status or metadata.",
)
async def update_discovery_run(
    run_id: UUID,
    data: DiscoveryRunUpdate,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """Update a discovery run."""
    repository = DiscoveryRunRepository(session)
    run = await repository.get(run_id)

    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery run {run_id} not found",
        )

    update_data = data.model_dump(exclude_unset=True)
    run = await repository.update(run, update_data)
    await session.commit()
    await session.refresh(run)

    return run


@router.get(
    "/runs/{run_id}/windows",
    response_model=list[DiscoveryWindowRead],
    summary="List discovery windows",
    description="List all windows for a discovery run.",
)
async def list_discovery_windows(
    run_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[DiscoveryWindow]:
    """List windows for a discovery run."""
    repository = DiscoveryWindowRepository(session)
    return await repository.get_by_run_id(run_id)


@router.get(
    "/windows/{window_id}",
    response_model=DiscoveryWindowRead,
    summary="Get a discovery window",
    description="Get details of a specific discovery window.",
)
async def get_discovery_window(
    window_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> DiscoveryWindow:
    """Get a discovery window by ID."""
    repository = DiscoveryWindowRepository(session)
    window = await repository.get(window_id)

    if not window:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Discovery window {window_id} not found",
        )

    return window


@router.get(
    "/runs/{run_id}/candidates",
    response_model=list[ClipCandidateRead],
    summary="List clip candidates",
    description="List all candidates for a discovery run.",
)
async def list_clip_candidates(
    run_id: UUID,
    exclude_duplicates: bool = Query(False, description="Exclude duplicate candidates"),
    session: AsyncSession = Depends(get_session),
) -> list[ClipCandidate]:
    """List candidates for a discovery run."""
    repository = ClipCandidateRepository(session)

    if exclude_duplicates:
        return await repository.get_non_duplicate_by_run_id(run_id)

    return await repository.get_by_run_id(run_id)


@router.get(
    "/candidates/{candidate_id}",
    response_model=ClipCandidateRead,
    summary="Get a clip candidate",
    description="Get details of a specific clip candidate.",
)
async def get_clip_candidate(
    candidate_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> ClipCandidate:
    """Get a clip candidate by ID."""
    repository = ClipCandidateRepository(session)
    candidate = await repository.get(candidate_id)

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
    description="Update candidate selection status or score.",
)
async def update_clip_candidate(
    candidate_id: UUID,
    data: ClipCandidateUpdate,
    session: AsyncSession = Depends(get_session),
) -> ClipCandidate:
    """Update a clip candidate."""
    repository = ClipCandidateRepository(session)
    candidate = await repository.get(candidate_id)

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip candidate {candidate_id} not found",
        )

    update_data = data.model_dump(exclude_unset=True)
    candidate = await repository.update(candidate, update_data)
    await session.commit()
    await session.refresh(candidate)

    return candidate


@router.post(
    "/candidates/{candidate_id}/select",
    response_model=ClipCandidateRead,
    summary="Select a clip candidate",
    description="Mark a candidate as selected for rendering.",
)
async def select_clip_candidate(
    candidate_id: UUID,
    rank: int | None = Query(None, ge=1, description="Selection rank"),
    session: AsyncSession = Depends(get_session),
) -> ClipCandidate:
    """Select a clip candidate for rendering."""
    repository = ClipCandidateRepository(session)
    candidate = await repository.get(candidate_id)

    if not candidate:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Clip candidate {candidate_id} not found",
        )

    if candidate.is_duplicate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot select a duplicate candidate",
        )

    candidate.selected = True
    if rank:
        candidate.selection_rank = rank
    candidate.updated_at = datetime.now(UTC)

    await session.commit()
    await session.refresh(candidate)

    return candidate
