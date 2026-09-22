"""ClipSource service."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.idempotency import compute_request_fingerprint, validate_idempotency
from app.clients.media_indexer_client import MediaIndexerClient
from app.models.entities import ClipSource
from app.repositories.clip_source_repository import ClipSourceRepository
from app.repositories.source_policy_repository import SourcePolicyRepository
from app.schemas.clip_source import (
    ClipSourceCreate,
    ClipSourceFromMediaSessionRequest,
    ClipSourceUpdate,
)
from app.services.base import BaseService
from app.services.policy_eligibility_service import (
    PolicyEligibilityService,
    PolicyViolationError,
)


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

            # Source admission validation using PolicyEligibilityService
            # This checks basic eligibility (verified, derivatives_allowed)
            # Full clip production validation happens at clip creation time
            eligibility_service = PolicyEligibilityService()
            try:
                eligibility_service.validate_for_source_admission(policy)
            except PolicyViolationError as e:
                raise ValidationError(f"Policy validation failed: {e.reason}") from e

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
        """Update a source.

        If source_policy_id is changed, rights_status is re-evaluated atomically.
        """
        source = await self.get(source_id)
        update_data = data.model_dump(exclude_unset=True)

        # Revalidate policy if changed
        if "source_policy_id" in update_data:
            new_policy_id = update_data["source_policy_id"]

            if new_policy_id is None:
                # Policy removed - rights become unverified
                update_data["rights_status"] = "unverified"
            else:
                # Fetch and validate new policy
                policy = await self.policy_repository.get(new_policy_id)
                if not policy:
                    raise PolicyNotFoundError(f"Policy {new_policy_id} not found")

                # Validate policy for source admission
                eligibility_service = PolicyEligibilityService()
                try:
                    eligibility_service.validate_for_source_admission(policy)
                    update_data["rights_status"] = "verified"
                except PolicyViolationError as e:
                    # Policy is valid but not eligible - set appropriate status
                    if policy.verification_status == "blocked":
                        update_data["rights_status"] = "blocked"
                    else:
                        update_data["rights_status"] = "unverified"

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

    async def create_from_media_session(
        self,
        data: ClipSourceFromMediaSessionRequest,
        media_indexer_client: MediaIndexerClient,
        idempotency_key: str | None = None,
    ) -> ClipSource:
        """Create a ClipSource from an existing Media Indexer session.

        This method:
        1. Queries Media Indexer to validate the session exists
        2. Validates policy eligibility (if safe_automated mode)
        3. Creates the ClipSource with media_session_id reference
        4. Handles idempotency to prevent duplicate creation

        Args:
            data: Request data with media_session_id and mode
            media_indexer_client: HTTP client for Media Indexer API
            idempotency_key: Optional idempotency key for replay protection

        Returns:
            Created or existing ClipSource

        Raises:
            MediaIndexerAPIError: If session not found or API error
            ValidationError: If policy validation fails
            IdempotencyConflictError: If idempotency key reused with different data
        """
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

        # Check for existing ClipSource with this media_session_id
        existing_by_session = await self.repository.get_by_media_session_id(
            data.media_session_id
        )
        if existing_by_session:
            # Idempotent: return existing source for this media_session_id
            return existing_by_session

        # Query Media Indexer to validate session exists and get metadata
        try:
            session_info = await media_indexer_client.get_session(data.media_session_id)
        except Exception as e:
            raise ValidationError(
                f"Failed to retrieve Media Indexer session {data.media_session_id}: {e}"
            ) from e

        # Validate mode requirements
        if data.mode == "safe_automated":
            if not data.source_policy_id:
                raise ValidationError("safe_automated mode requires a source_policy_id")

            policy = await self.policy_repository.get(data.source_policy_id)
            if not policy:
                raise PolicyNotFoundError(f"Policy {data.source_policy_id} not found")

            eligibility_service = PolicyEligibilityService()
            try:
                eligibility_service.validate_for_source_admission(policy)
            except PolicyViolationError as e:
                raise ValidationError(f"Policy validation failed: {e.reason}") from e

            create_data["rights_status"] = "verified"

        elif data.mode == "manual_override":
            if not data.operator_acknowledged:
                raise ValidationError("manual_override mode requires operator_acknowledged=true")
            create_data["rights_status"] = "unverified"

        # Populate fields from Media Indexer session
        create_data["status"] = "pending"
        create_data["media_session_id"] = data.media_session_id
        create_data["media_id"] = session_info.media_id

        # Set title from session label if not provided
        if not create_data.get("title"):
            create_data["title"] = session_info.label

        # Create the source
        source = await self.repository.create(create_data)
        return source
