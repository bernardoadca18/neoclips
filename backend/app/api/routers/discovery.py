"""API endpoints for clip discovery (Stage 3)."""

import hashlib
import logging
from datetime import UTC, datetime
from math import ceil
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
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
from app.services.clip_workflow_service import ClipWorkflowService

logger = logging.getLogger(__name__)
settings = get_settings()

# Window configuration
WINDOW_DURATION_SECONDS = 300.0
WINDOW_OVERLAP_SECONDS = 60.0


router = APIRouter(prefix="/v1/discovery", tags=["discovery"])


@router.post(
    "/workflows/{workflow_id}/discover",
    response_model=DiscoveryRunRead,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
    summary="Start clip discovery for a workflow (deprecated)",
    description="DEPRECATED: Use POST /v1/workflows/{workflow_id}/discover instead. This endpoint will be removed in a future version.",
)
async def start_discovery(
    workflow_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> DiscoveryRun:
    """
    Start clip discovery for a workflow.

    This endpoint creates a DiscoveryRun synchronously with idempotency support,
    creates discovery windows based on transcription duration, and dispatches
    the first window processing task.

    Idempotency:
    - If Idempotency-Key header is provided and a run exists with that key:
      - Same config (fingerprint match): returns existing run (200)
      - Different config (fingerprint mismatch): returns 409 Conflict
    - Uses unique constraint on idempotency_key to prevent duplicates.

    Returns:
        DiscoveryRun with status 'running' and window counts populated.
    """
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

    # Get transcription from Media Indexer (just metadata, not segments)
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

    if not transcription.duration_seconds or transcription.duration_seconds <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Transcription has no valid duration",
        )

    # Get LLM model from settings (matches LiteLLMHTTPDiscoveryProvider default)
    # Format: "provider/model" e.g., "openai/gpt-4o-mini"
    litellm_model = settings.litellm_model
    if "/" in litellm_model:
        llm_provider, llm_model_name = litellm_model.split("/", 1)
    else:
        llm_provider = "openai"
        llm_model_name = litellm_model

    # Discovery strategy configuration (hardcoded for MVP, could be parameterized later)
    strategy_id = "transcript_v1"
    strategy_version = "1.0.0"
    prompt_id = "clip_discovery_v1"
    prompt_version = "1.0.0"

    # Compute canonical request fingerprint from source + transcription + discovery config
    # This captures the full execution identity so same source+config produces same fingerprint
    fingerprint_data = (
        f"{source.id}:{source.transcription_id}:{source.source_sha256 or ''}"
        f":{strategy_id}:{strategy_version}:{prompt_id}:{prompt_version}"
        f":{llm_provider}:{llm_model_name}"
    )
    request_fingerprint = hashlib.sha256(fingerprint_data.encode()).hexdigest()

    # Check idempotency - handle existing runs
    if idempotency_key:
        result = await session.execute(
            select(DiscoveryRun).where(DiscoveryRun.idempotency_key == idempotency_key)
        )
        existing_run = result.scalar_one_or_none()
        if existing_run:
            # Check if config matches (same fingerprint)
            if existing_run.request_fingerprint == request_fingerprint:
                # Same key, same config - return existing run
                logger.info(f"Returning existing discovery run for idempotency key {idempotency_key[:8]}...")
                return existing_run
            else:
                # Same key, different config - 409 Conflict
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Idempotency key already used with different configuration",
                )

    # Build windows by duration (no segment loading)
    duration = transcription.duration_seconds
    effective_window_size = WINDOW_DURATION_SECONDS - WINDOW_OVERLAP_SECONDS
    window_count = max(1, ceil((duration - WINDOW_OVERLAP_SECONDS) / effective_window_size))

    windows_to_create = []
    for i in range(window_count):
        start = i * effective_window_size
        end = min(start + WINDOW_DURATION_SECONDS, duration)

        windows_to_create.append({
            "window_index": i,
            "start_seconds": start,
            "end_seconds": end,
        })

        # Last window reached the end
        if end >= duration:
            break

    # Create DiscoveryRun (using LLM model extracted earlier for fingerprint)
    run = DiscoveryRun(
        id=uuid4(),
        workflow_id=workflow_id,
        source_id=source.id,
        transcription_id=transcription.id,
        idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint,
        status="running",
        profile="transcript_only",
        strategy_id=strategy_id,
        strategy_version=strategy_version,
        prompt_id=prompt_id,
        prompt_version=prompt_version,
        llm_model=llm_model_name,
        llm_provider=llm_provider,
        total_windows=len(windows_to_create),
        processed_windows=0,
        completed_windows=0,
        failed_windows=0,
        total_candidates=0,
        started_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(run)

    # Try to flush - handle IntegrityError for duplicate idempotency_key
    try:
        await session.flush()
    except IntegrityError:
        # Race condition: another request created the run
        await session.rollback()
        if idempotency_key:
            result = await session.execute(
                select(DiscoveryRun).where(DiscoveryRun.idempotency_key == idempotency_key)
            )
            existing_run = result.scalar_one_or_none()
            if existing_run:
                if existing_run.request_fingerprint == request_fingerprint:
                    return existing_run
                else:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency key already used with different configuration",
                    )
        raise

    # Create DiscoveryWindows
    db_windows = []
    for window_data in windows_to_create:
        db_window = DiscoveryWindow(
            id=uuid4(),
            run_id=run.id,
            window_index=window_data["window_index"],
            start_seconds=window_data["start_seconds"],
            end_seconds=window_data["end_seconds"],
            segment_count=0,  # Will be populated when processing
            status="pending",
            attempt_count=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_windows.append(db_window)
        session.add(db_window)

    # Update workflow state using service
    workflow_service = ClipWorkflowService(session)
    await workflow_service.transition_status(workflow.id, "discovering")

    # Commit run and windows before dispatching task
    await session.commit()

    # Bootstrap: schedule ONLY the first pending window
    if db_windows:
        from app.tasks.discovery_tasks import process_window

        first_window = db_windows[0]
        process_window.delay(str(first_window.id), str(run.id))
        logger.info(f"Created discovery run {run.id} with {len(db_windows)} windows, dispatched first window {first_window.id}")

    await session.refresh(run)
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
