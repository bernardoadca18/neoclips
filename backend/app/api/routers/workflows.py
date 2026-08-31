"""ClipWorkflow API router."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
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


class DiscoverRequest(BaseModel):
    """Request body for triggering discovery."""

    profile: str | None = Field(
        default="default",
        description="Discovery profile to use",
    )
    window_duration_seconds: float | None = Field(
        default=300.0,
        description="Duration of each discovery window in seconds",
    )
    overlap_seconds: float | None = Field(
        default=60.0,
        description="Overlap between windows in seconds",
    )


class DiscoverResponse(BaseModel):
    """Response for discovery trigger."""

    workflow_id: UUID
    task_id: str | None = None
    status: str
    message: str

    model_config = {"extra": "forbid"}


@router.post(
    "/{workflow_id}/discover",
    response_model=DiscoverResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger clip discovery for a workflow",
    description="Start the discovery process for a workflow. Returns immediately with task ID.",
)
async def trigger_discovery(
    workflow_id: UUID,
    data: DiscoverRequest = Depends(),
    session: AsyncSession = Depends(get_session),
) -> DiscoverResponse:
    """Trigger clip discovery for a workflow.

    This endpoint validates the workflow is ready for discovery and
    queues the discovery task. The actual discovery runs asynchronously.

    The workflow's source must be in 'ready_for_discovery' status.

    Returns 202 Accepted with the Celery task ID for tracking.
    """
    from sqlalchemy import select

    from app.models.entities import ClipSource, ClipWorkflow

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

    # Check source is ready
    if source.status != "ready_for_discovery":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Source status is '{source.status}', must be 'ready_for_discovery'",
        )

    # Check source has transcription
    if not source.transcription_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source has no transcription_id",
        )

    # Queue the discovery task
    from app.tasks.discovery_tasks import run_discovery

    task = run_discovery.delay(str(workflow_id))

    return DiscoverResponse(
        workflow_id=workflow_id,
        task_id=task.id,
        status="queued",
        message=f"Discovery task {task.id} queued for workflow {workflow_id}",
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
