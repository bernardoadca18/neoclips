"""ClipWorkflow API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.clip_workflow import ClipWorkflowCreate, ClipWorkflowResponse, ClipWorkflowUpdate
from app.services.clip_workflow_service import (
    ClipWorkflowService,
    IdempotencyConflictError,
    InvalidStateTransitionError,
    SourceNotFoundError,
    WorkflowAlreadyExistsError,
    WorkflowNotFoundError,
)

router = APIRouter(prefix="/v1/workflows", tags=["workflows"])


class DiscoverResponse(BaseModel):
    """Response for discovery trigger."""

    id: UUID
    workflow_id: UUID
    status: str
    profile: str
    llm_model: str | None
    llm_provider: str | None
    total_windows: int
    processed_windows: int
    completed_windows: int
    failed_windows: int
    total_candidates: int
    idempotency_key: str | None
    request_fingerprint: str | None
    error_message: str | None

    model_config = {"extra": "forbid"}


@router.post(
    "/{workflow_id}/discover",
    response_model=DiscoverResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Start clip discovery for a workflow",
    description="Create a discovery run with idempotency and dispatch window processing tasks.",
)
async def trigger_discovery(
    workflow_id: UUID,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_session),
) -> DiscoverResponse:
    """
    Start clip discovery for a workflow.

    This endpoint creates a DiscoveryRun synchronously with idempotency support,
    creates discovery windows based on transcription duration, and dispatches
    the first window processing task.

    Idempotency:
    - If Idempotency-Key header is provided and a run exists with that key:
      - Same config (fingerprint match): returns existing run (201)
      - Different config (fingerprint mismatch): returns 409 Conflict
    - Uses unique constraint on idempotency_key to prevent duplicates.

    Returns:
        DiscoveryRun with status 'running' and window counts populated.
    """
    import hashlib
    import logging
    from datetime import UTC, datetime
    from math import ceil
    from uuid import uuid4

    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from app.clients.media_indexer_client import MediaIndexerClient
    from app.core.config import get_settings
    from app.models.entities import ClipSource, ClipWorkflow, DiscoveryRun, DiscoveryWindow

    logger = logging.getLogger(__name__)
    settings = get_settings()

    # Window configuration
    WINDOW_DURATION_SECONDS = 300.0
    WINDOW_OVERLAP_SECONDS = 60.0

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

    # Compute canonical request fingerprint from source + transcription state
    fingerprint_data = f"{source.id}:{source.transcription_id}:{source.source_sha256 or ''}"
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
                return DiscoverResponse(
                    id=existing_run.id,
                    workflow_id=existing_run.workflow_id,
                    status=existing_run.status,
                    profile=existing_run.profile,
                    llm_model=existing_run.llm_model,
                    llm_provider=existing_run.llm_provider,
                    total_windows=existing_run.total_windows,
                    processed_windows=existing_run.processed_windows,
                    completed_windows=existing_run.completed_windows,
                    failed_windows=existing_run.failed_windows,
                    total_candidates=existing_run.total_candidates,
                    idempotency_key=existing_run.idempotency_key,
                    request_fingerprint=existing_run.request_fingerprint,
                    error_message=existing_run.error_message,
                )
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
                    return DiscoverResponse(
                        id=existing_run.id,
                        workflow_id=existing_run.workflow_id,
                        status=existing_run.status,
                        profile=existing_run.profile,
                        llm_model=existing_run.llm_model,
                        llm_provider=existing_run.llm_provider,
                        total_windows=existing_run.total_windows,
                        processed_windows=existing_run.processed_windows,
                        completed_windows=existing_run.completed_windows,
                        failed_windows=existing_run.failed_windows,
                        total_candidates=existing_run.total_candidates,
                        idempotency_key=existing_run.idempotency_key,
                        request_fingerprint=existing_run.request_fingerprint,
                        error_message=existing_run.error_message,
                    )
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

    return DiscoverResponse(
        id=run.id,
        workflow_id=run.workflow_id,
        status=run.status,
        profile=run.profile,
        llm_model=run.llm_model,
        llm_provider=run.llm_provider,
        total_windows=run.total_windows,
        processed_windows=run.processed_windows,
        completed_windows=run.completed_windows,
        failed_windows=run.failed_windows,
        total_candidates=run.total_candidates,
        idempotency_key=run.idempotency_key,
        request_fingerprint=run.request_fingerprint,
        error_message=run.error_message,
    )


def get_workflow_service(session: AsyncSession = Depends(get_session)) -> ClipWorkflowService:
    """Get ClipWorkflowService instance."""
    return ClipWorkflowService(session)


@router.post(
    "/",
    response_model=ClipWorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new workflow",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Source not found"},
        status.HTTP_409_CONFLICT: {"description": "Workflow already exists for source"},
    },
)
async def create_workflow(
    data: ClipWorkflowCreate,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> ClipWorkflowResponse:
    """
    Create a new clip workflow.

    Supports idempotency via Idempotency-Key header.
    For MVP, only one workflow per source is allowed.
    """
    try:
        workflow = await service.create(data, idempotency_key=idempotency_key)
        return ClipWorkflowResponse.model_validate(workflow)
    except SourceNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except WorkflowAlreadyExistsError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "category": "conflict",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except IdempotencyConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "error": {
                    "category": "idempotency_conflict",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.get(
    "/{workflow_id}",
    response_model=ClipWorkflowResponse,
    summary="Get workflow by ID",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Workflow not found"},
    },
)
async def get_workflow(
    workflow_id: UUID,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> ClipWorkflowResponse:
    """Get a workflow by ID."""
    try:
        workflow = await service.get(workflow_id)
        return ClipWorkflowResponse.model_validate(workflow)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.get(
    "/",
    response_model=list[ClipWorkflowResponse],
    summary="List all workflows",
)
async def list_workflows(
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> list[ClipWorkflowResponse]:
    """List all workflows with pagination."""
    if status_filter:
        workflows = await service.repository.get_by_status(status_filter, limit=limit)
    else:
        workflows = await service.get_all(limit=limit, offset=offset)
    return [ClipWorkflowResponse.model_validate(w) for w in workflows]


@router.patch(
    "/{workflow_id}",
    response_model=ClipWorkflowResponse,
    summary="Update a workflow",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Workflow not found"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid state transition"},
    },
)
async def update_workflow(
    workflow_id: UUID,
    data: ClipWorkflowUpdate,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> ClipWorkflowResponse:
    """Update a workflow."""
    try:
        workflow = await service.update(workflow_id, data)
        return ClipWorkflowResponse.model_validate(workflow)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except InvalidStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.delete(
    "/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a workflow",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Workflow not found"},
    },
)
async def delete_workflow(
    workflow_id: UUID,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> None:
    """Delete a workflow."""
    try:
        await service.delete(workflow_id)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.post(
    "/{workflow_id}/cancel",
    response_model=ClipWorkflowResponse,
    summary="Cancel a workflow",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Workflow not found"},
        status.HTTP_400_BAD_REQUEST: {"description": "Invalid state transition"},
    },
)
async def cancel_workflow(
    workflow_id: UUID,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> ClipWorkflowResponse:
    """Cancel a workflow."""
    try:
        workflow = await service.cancel(workflow_id)
        return ClipWorkflowResponse.model_validate(workflow)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except InvalidStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.post(
    "/{workflow_id}/retry",
    response_model=ClipWorkflowResponse,
    summary="Retry a failed workflow",
    responses={
        status.HTTP_404_NOT_FOUND: {"description": "Workflow not found"},
        status.HTTP_400_BAD_REQUEST: {"description": "Workflow is not in failed state"},
    },
)
async def retry_workflow(
    workflow_id: UUID,
    service: ClipWorkflowService = Depends(get_workflow_service),
) -> ClipWorkflowResponse:
    """Retry a failed workflow."""
    try:
        workflow = await service.retry(workflow_id)
        return ClipWorkflowResponse.model_validate(workflow)
    except WorkflowNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "category": "not_found",
                    "message": str(e),
                    "details": {},
                }
            },
        )
    except InvalidStateTransitionError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "category": "validation_error",
                    "message": str(e),
                    "details": {},
                }
            },
        )
