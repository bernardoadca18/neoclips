"""ClipSource service."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import compute_request_fingerprint, validate_idempotency
from app.models.entities import ClipSource
from app.repositories.clip_source_repository import ClipSourceRepository
from app.repositories.source_policy_repository import SourcePolicyRepository
from app.schemas.clip_source import ClipSourceCreate, ClipSourceUpdate
from app.services.base import BaseService


class SourceNotFoundError(Exception):
    """Raised when source is not found."""
    pass


class PolicyNotFoundError(Exception):
    """Raised when policy is not found."""
    pass


class ValidationError(Exception):
    """Raised when validation fails."""
    pass


class IdempotencyConflictError(Exception):
    """Raised when idempotency key is reused with different request data."""
    pass


class ClipSourceService(BaseService[ClipSourceRepository]):
    """Service for ClipSource business logic."""

    def __init__(self, session: AsyncSession) -> None:
        repository = ClipSourceRepository(session)
        super().__init__(session, repository)
        self.policy_repository = SourcePolicyRepository(session)

    async def create(
        self,
        data: ClipSourceCreate,
        idempotency_key: str | None = None,
    ) -> ClipSource:
        """Create a new source with optional idempotency."""
        create_data = data.model_dump()

        # Handle idempotency
        if idempotency_key:
            fingerprint = compute_request_fingerprint(create_data)
            existing = await self.repository.get_by_idempotency_key(idempotency_key)

            if existing:
                is_match, is_conflict = validate_idempotency(
                    existing.idempotency_key,
                    existing.request_fingerprint,
                    idempotency_key,
                    fingerprint,
                )
                if is_conflict:
                    raise IdempotencyConflictError(
                        f"Idempotency key '{idempotency_key}' already used with different request data"
                    )
                if is_match:
                    return existing  # Idempotent replay

            create_data["idempotency_key"] = idempotency_key
            create_data["request_fingerprint"] = fingerprint

        # Validate mode requirements
        if data.mode == "safe_automated":
            if not data.source_policy_id:
                raise ValidationError("safe_automated mode requires a source_policy_id")

            policy = await self.policy_repository.get(data.source_policy_id)
            if not policy:
                raise PolicyNotFoundError(f"Policy {data.source_policy_id} not found")

            if policy.verification_status != "verified":
                raise ValidationError("safe_automated mode requires a verified policy")

            create_data["rights_status"] = "verified"

        elif data.mode == "manual_override":
            if not data.operator_acknowledged:
                raise ValidationError("manual_override mode requires operator_acknowledged=true")
            create_data["rights_status"] = "unverified"

        create_data["status"] = "pending"
        source = await self.repository.create(create_data)
        return source

    async def get(self, source_id: UUID) -> ClipSource:
        """Get source by ID."""
        source = await self.repository.get(source_id)
        if not source:
            raise SourceNotFoundError(f"Source {source_id} not found")
        return source

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[ClipSource]:
        """Get all sources."""
        return await self.repository.get_all(limit=limit, offset=offset)

    async def update(self, source_id: UUID, data: ClipSourceUpdate) -> ClipSource:
        """Update a source."""
        source = await self.get(source_id)
        update_data = data.model_dump(exclude_unset=True)
        source = await self.repository.update(source, update_data)
        return source

    async def delete(self, source_id: UUID) -> None:
        """Delete a source."""
        source = await self.get(source_id)
        await self.repository.delete(source)

    async def update_status(self, source_id: UUID, status: str) -> ClipSource:
        """Update source status."""
        source = await self.get(source_id)
        source = await self.repository.update(source, {"status": status})
        return source

    async def get_by_status(self, status: str) -> list[ClipSource]:
        """Get sources by status."""
        return await self.repository.get_by_status(status)
