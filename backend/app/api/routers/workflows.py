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
    status_code=status.HTTP_202_ACCEPTED,
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
      - Same config (fingerprint match): returns existing run (202)
      - Different config (fingerprint mismatch): returns 409 Conflict
    - Uses unique constraint on idempotency_key to prevent duplicates.

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
