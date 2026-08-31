"""WorkflowErrorHistory service."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import WorkflowErrorHistory
from app.repositories.workflow_error_history_repository import WorkflowErrorHistoryRepository
from app.services.base import BaseService


class WorkflowErrorHistoryService(BaseService[WorkflowErrorHistoryRepository]):
    """Service for WorkflowErrorHistory operations."""

    def __init__(self, session: AsyncSession) -> None:
        repository = WorkflowErrorHistoryRepository(session)
        super().__init__(session, repository)

    async def record_error(
        self,
        workflow_id: UUID,
        phase: str,
        category: str,
        message: str,
        attempt: int,
    ) -> WorkflowErrorHistory:
        """Record a workflow error to history.

        Args:
            workflow_id: UUID of the workflow
            phase: Current phase when error occurred
            category: Error category (e.g., "transient", "permanent", "external")
            message: Human-readable error message (no stack traces)
            attempt: Attempt number when error occurred

        Returns:
            Created WorkflowErrorHistory entity
        """
        return await self.repository.create({
            "workflow_id": workflow_id,
            "phase": phase,
            "category": category,
            "message": message,
            "attempt": attempt,
        })

    async def get_workflow_errors(
        self, workflow_id: UUID, limit: int = 100
    ) -> list[WorkflowErrorHistory]:
        """Get error history for a workflow.

        Args:
            workflow_id: UUID of the workflow
            limit: Maximum number of errors to return

        Returns:
            List of WorkflowErrorHistory entries, newest first
        """
        return await self.repository.get_by_workflow(workflow_id, limit=limit)
