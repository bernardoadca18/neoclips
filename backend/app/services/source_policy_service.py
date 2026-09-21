"""SourcePolicy service."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import SourcePolicy
from app.repositories.source_policy_repository import SourcePolicyRepository
from app.schemas.source_policy import SourcePolicyCreate, SourcePolicyUpdate
from app.services.base import BaseService


class PolicyNotFoundError(Exception):
    """Raised when policy is not found."""
    pass


class PolicyAlreadyExistsError(Exception):
    """Raised when policy with same name/version already exists."""
    pass


class PolicyInUseError(Exception):
    """Raised when attempting to delete a policy that is in use."""
    pass


class SourcePolicyService(BaseService[SourcePolicyRepository]):
    """Service for SourcePolicy business logic."""

    def __init__(self, session: AsyncSession) -> None:
        repository = SourcePolicyRepository(session)
        super().__init__(session, repository)

    async def create(self, data: SourcePolicyCreate) -> SourcePolicy:
        """Create a new policy."""
        # Check for existing policy with same name/version
        existing = await self.repository.get_by_name_version(data.name, data.version)
        if existing:
            raise PolicyAlreadyExistsError(
                f"Policy with name '{data.name}' and version '{data.version}' already exists"
            )

        policy = await self.repository.create(data.model_dump())
        return policy

    async def get(self, policy_id: UUID) -> SourcePolicy:
        """Get policy by ID."""
        policy = await self.repository.get(policy_id)
        if not policy:
            raise PolicyNotFoundError(f"Policy {policy_id} not found")
        return policy

    async def get_all(self, limit: int = 100, offset: int = 0) -> list[SourcePolicy]:
        """Get all policies."""
        return await self.repository.get_all(limit=limit, offset=offset)

    async def update(self, policy_id: UUID, data: SourcePolicyUpdate) -> SourcePolicy:
        """Update a policy."""
        policy = await self.get(policy_id)
        update_data = data.model_dump(exclude_unset=True)

        # If verification_status is being set to verified, set verified_at
        if update_data.get("verification_status") == "verified":
            update_data["verified_at"] = datetime.now(UTC)

        policy = await self.repository.update(policy, update_data)
        return policy

    async def delete(self, policy_id: UUID) -> None:
        """Delete a policy.

        Raises PolicyInUseError if the policy is referenced by any ClipSource.
        This protects provenance and lineage.
        """
        policy = await self.get(policy_id)

        # Check if policy is in use
        from app.repositories.clip_source_repository import ClipSourceRepository
        source_repo = ClipSourceRepository(self.session)
        sources_using_policy = await source_repo.get_by_policy(policy_id)

        if sources_using_policy:
            raise PolicyInUseError(
                f"Cannot delete policy {policy_id}: it is referenced by "
                f"{len(sources_using_policy)} source(s)"
            )

        await self.repository.delete(policy)

    async def verify(self, policy_id: UUID, evidence_uri: str | None = None, evidence_note: str | None = None) -> SourcePolicy:
        """Mark a policy as verified."""
        policy = await self.get(policy_id)
        update_data = {
            "verification_status": "verified",
            "verified_at": datetime.now(UTC),
        }
        if evidence_uri:
            update_data["evidence_uri"] = evidence_uri
        if evidence_note:
            update_data["evidence_note"] = evidence_note

        policy = await self.repository.update(policy, update_data)
        return policy

    async def block(self, policy_id: UUID, reason: str | None = None) -> SourcePolicy:
        """Block a policy."""
        policy = await self.get(policy_id)
        update_data = {
            "verification_status": "blocked",
        }
        if reason:
            update_data["evidence_note"] = reason

        policy = await self.repository.update(policy, update_data)
        return policy
