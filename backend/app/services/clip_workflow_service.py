"""ClipWorkflow service."""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipWorkflow
from app.repositories.clip_workflow_repository import ClipWorkflowRepository
from app.repositories.clip_source_repository import ClipSourceRepository
from app.schemas.clip_workflow import ClipWorkflowCreate, ClipWorkflowUpdate
from app.services.base import BaseService


class WorkflowNotFoundError(Exception):
    """Raised when workflow is not found."""
    pass


class SourceNotFoundError(Exception):
    """Raised when source is not found."""
    pass


class InvalidStateTransitionError(Exception):
    """Raised when state transition is invalid."""
    pass


class WorkflowAlreadyExistsError(Exception):
    """Raised when workflow already exists for the source."""
    pass


# Valid state transitions for ClipWorkflow
VALID_TRANSITIONS: dict[str, set[str]] = {
    "created": {"ingesting", "cancelled"},
    "ingesting": {"transcribing", "failed", "blocked", "cancelled"},
    "transcribing": {"discovering", "failed", "blocked", "cancelled"},
    "discovering": {"observing", "reranking", "awaiting_selection", "failed", "cancelled"},
    "observing": {"reranking", "awaiting_selection", "failed", "cancelled"},
    "reranking": {"awaiting_selection", "failed", "cancelled"},
    "awaiting_selection": {"rendering", "cancelled"},
    "rendering": {"packaging", "failed", "cancelled"},
    "packaging": {"qa", "failed", "cancelled"},
    "qa": {"ready_for_review", "failed", "blocked", "cancelled"},
    "failed": {"created"},  # retry
    "blocked": set(),  # terminal
    "cancelled": set(),  # terminal
    "ready_for_review": set(),  # terminal
}


class ClipWorkflowService(BaseService[ClipWorkflowRepository]):
    """Service for ClipWorkflow business logic."""

    def __init__(self, session: AsyncSession) -> None:
        repository = ClipWorkflowRepository(session)
        super().__init__(session, repository)
        self.source_repository = ClipSourceRepository(session)

    async def create(
        self,
        data: ClipWorkflowCreate,
        idempotency_key: str | None = None,
    ) -> ClipWorkflow:
        """
        Create a new workflow.

        For MVP, we enforce one workflow per source.
        Idempotency is based on source_id.
        """
        # Check source exists
        source = await self.source_repository.get(data.source_id)
        if not source:
            raise SourceNotFoundError(f"Source {data.source_id} not found")

        # Check for existing workflow (idempotency)
        existing = await self.repository.get_by_idempotency_key(
            data.source_id,
            idempotency_key or "",
        )
        if existing:
            raise WorkflowAlreadyExistsError(
                f"Workflow already exists for source {data.source_id}"
            )

        create_data = {
            "source_id": data.source_id,
            "status": "created",
            "attempt_count": 0,
        }
        workflow = await self.repository.create(create_data)
        return workflow

    async def get(self, workflow_id: UUID) -> ClipWorkflow:
        """Get workflow by ID."""
        workflow = await self.repository.get(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow {workflow_id} not found")
        return workflow

    async def get_by_source(self, source_id: UUID) -> list[ClipWorkflow]:
        """Get workflows by source ID."""
        return await self.repository.get_by_source(source_id)

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[ClipWorkflow]:
        """Get all workflows."""
        return await self.repository.get_all(limit=limit, offset=offset)

    async def update(self, workflow_id: UUID, data: ClipWorkflowUpdate) -> ClipWorkflow:
        """Update a workflow."""
        workflow = await self.get(workflow_id)
        update_data = data.model_dump(exclude_unset=True)

        # Validate state transition if status is being changed
        if "status" in update_data:
            self._validate_transition(workflow.status, update_data["status"])

        workflow = await self.repository.update(workflow, update_data)
        return workflow

    async def transition_status(
        self,
        workflow_id: UUID,
        new_status: str,
        error_category: str | None = None,
        error_message: str | None = None,
    ) -> ClipWorkflow:
        """Transition workflow to a new status."""
        workflow = await self.get(workflow_id)
        self._validate_transition(workflow.status, new_status)

        update_data: dict[str, Any] = {"status": new_status}

        # Handle started_at
        if new_status not in {"created", "cancelled"} and not workflow.started_at:
            update_data["started_at"] = datetime.now(timezone.utc)

        # Handle completed_at for terminal states
        if new_status in {"ready_for_review", "blocked", "cancelled"}:
            update_data["completed_at"] = datetime.now(timezone.utc)

        # Handle error info
        if error_category:
            update_data["last_error_category"] = error_category
        if error_message:
            update_data["last_error_message"] = error_message

        # Increment attempt count on retry
        if workflow.status == "failed" and new_status == "created":
            update_data["attempt_count"] = workflow.attempt_count + 1

        workflow = await self.repository.update(workflow, update_data)
        return workflow

    async def cancel(self, workflow_id: UUID) -> ClipWorkflow:
        """Cancel a workflow."""
        return await self.transition_status(workflow_id, "cancelled")

    async def retry(self, workflow_id: UUID) -> ClipWorkflow:
        """Retry a failed workflow."""
        workflow = await self.get(workflow_id)
        if workflow.status != "failed":
            raise InvalidStateTransitionError("Can only retry failed workflows")
        return await self.transition_status(workflow_id, "created")

    async def delete(self, workflow_id: UUID) -> None:
        """Delete a workflow."""
        workflow = await self.get(workflow_id)
        await self.repository.delete(workflow)

    def _validate_transition(self, current: str, new: str) -> None:
        """Validate state transition."""
        valid_next = VALID_TRANSITIONS.get(current, set())
        if new not in valid_next:
            raise InvalidStateTransitionError(
                f"Invalid transition from '{current}' to '{new}'"
            )
