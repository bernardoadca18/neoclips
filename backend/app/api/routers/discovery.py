"""API endpoints for clip discovery (Stage 3)."""

import hashlib
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.media_indexer_client import MediaIndexerClient
from app.core.config import get_settings
from app.core.database import get_session
from app.models.entities import (
    ClipCandidate,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    DiscoveryWindow,
)
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
from app.services.transcript_window_builder import TranscriptWindowBuilder, WindowConfig

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


@router.post(
    "/discover",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_201_CREATED,
    summary="Start clip discovery for a workflow",
    description="Create a discovery run with idempotency and dispatch window processing tasks.",
)
async def start_discovery(
    workflow_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """
    Start clip discovery for a workflow.

    This endpoint creates a DiscoveryRun synchronously with idempotency support,
    creates discovery windows, and dispatches one-window-per-task processing.

    Idempotency:
    - If Idempotency-Key header is provided and a run exists with that key,
      returns the existing run (200) instead of creating a new one.
    - Uses unique constraint on idempotency_key to prevent duplicates.

    Returns:
        DiscoveryRun with status 'running' and window counts populated.
    """
    # Check idempotency - return existing run if found
    if idempotency_key:
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.idempotency_key == idempotency_key)
        )
        existing_run = result.scalar_one_or_none()
        if existing_run:
            logger.info(f"Returning existing discovery run for idempotency key {idempotency_key[:8]}...")
            return existing_run

    # Get workflow
    result = await session.execute(
        select(ClipWorkflow).where(ClipWorkflow.id == workflow_id)
    )
    workflow = result.scalar_one_or_none()

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Workflow {workflow_id} not found",
        )

    # Get source
    result = await session.execute(
        select(ClipSource).where(ClipSource.id == workflow.source_id)
    )
    source = result.scalar_one_or_none()

    if not source:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source for workflow {workflow_id} not found",
        )

    if source.status != "ready_for_discovery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source status is {source.status}, must be ready_for_discovery",
        )

    if not source.transcription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source has no transcription_id",
        )

    # Compute request fingerprint from source + workflow state
    fingerprint_data = f"{source.id}:{source.transcription_id}:{source.source_sha256 or ''}"
    request_fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()

    # Get transcription from Media Indexer
    client = MediaIndexerClient(
        base_url=settings.media_indexer_base_url,
        timeout_seconds=settings.media_indexer_timeout_seconds,
    )

    try:
        transcription = await client.get_transcription(source.transcription_id)
    except Exception as e:
        logger.error(f"Failed to get transcription: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to get transcription from Media Indexer: {e}",
        )

    # Fetch segments to build windows
    try:
        segments = await client.get_transcript_segments(
            transcription_id=transcription.id,
            offset=0,
            limit=100000,  # Large limit for window building
        )
    except Exception as e:
        logger.error(f"Failed to get transcript segments: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to get transcript segments: {e}",
        )

    # Build windows
    window_builder = TranscriptWindowBuilder(WindowConfig(
        window_duration_seconds=300.0,
        overlap_seconds=60.0,
    ))
    windows = window_builder.build(segments)

    # Create DiscoveryRun
    run = DiscoveryRun(
        id=uuid4(),
        workflow_id=workflow_id,
        source_id=source.id,
        transcription_id=transcription.id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        status="running",
        profile="transcript_only",
        strategy_id="transcript_v1",
        strategy_version="1.0.0",
        prompt_id="clip_discovery_v1",
        prompt_version="1.0.0",
        llm_model="gpt-4o",
        llm_provider="openai",
        total_windows=len(windows),
        processed_windows=0,
        completed_windows=0,
        failed_windows=0,
        total_candidates=0,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)
    await session.flush()

    # Create DiscoveryWindows
    db_windows = []
    for window in windows:
        db_window = DiscoveryWindow(
            id=uuid4(),
            run_id=run.id,
            window_index=window.window_index,
            start_seconds=window.start_seconds,
            end_seconds=window.end_seconds,
            segment_count=window.segment_count,
            status="pending",
            attempt_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_windows.append(db_window)
        session.add(db_window)

    # Update workflow state
    workflow.current_phase = "discovering"
    workflow.updated_at = datetime.now(UTC)

    # Commit run and windows before dispatching tasks
    await session.commit()

    # Dispatch one-window-per-task
    from app.tasks.discovery_tasks import process_window

    for db_window in db_windows:
        process_window.delay(str(db_window.id), str(run.id))

    logger.info(f"Created discovery run {run.id} with {len(windows)} windows")

    await session.refresh(run)
    return run


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
