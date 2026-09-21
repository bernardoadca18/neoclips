"""Policy eligibility service for rights enforcement.

Validates that content usage complies with SourcePolicy constraints.
Implements fail-closed policy: deny if any check fails or is inconclusive.

Two distinct eligibility checks:
1. Source admission eligibility - validates at source creation time
2. Clip production eligibility - validates at clip creation time (requires context)
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.models.entities import SourcePolicy


class PolicyViolationError(Exception):
    """Raised when content usage violates policy constraints."""

    def __init__(self, reason: str, policy_id: UUID | None = None):
        self.reason = reason
        self.policy_id = policy_id
        super().__init__(f"Policy violation: {reason}")


class PolicyEligibilityService:
    """Validates content usage against SourcePolicy constraints.

    Implements a fail-closed policy: if any check fails or cannot be
    verified, the operation is denied. This prevents accidental misuse
    of content with unclear or restrictive rights.

    Two distinct eligibility checks:
    1. Source admission eligibility: Basic checks at source creation
       - Policy must be verified
       - Derivatives must be allowed (clips are derivative works)

    2. Clip production eligibility: Full context at clip creation
       - All source admission checks
       - Platform restrictions
       - Duration limits
       - Embargo enforcement
       - Commercial/monetization restrictions
       - Attribution acknowledgment
    """

    def validate_for_source_admission(
        self,
        policy: "SourcePolicy",
    ) -> None:
        """Validate policy for source admission (source creation time).

        This is a preliminary check that verifies the policy allows
        derivative works (clips). More detailed checks (platform, duration,
        embargo) happen at clip production time.

        Args:
            policy: The SourcePolicy to validate against

        Raises:
            PolicyViolationError: If policy does not allow derivative works
        """
        # Fail-closed: unverified policy always rejects
        if policy.verification_status != "verified":
            raise PolicyViolationError(
                f"Policy {policy.id} is not verified (status: {policy.verification_status})",
                policy_id=policy.id,
            )

        # Check derivatives allowed (clips are derivative works)
        if not policy.derivatives_allowed:
            raise PolicyViolationError(
                f"Policy {policy.id} does not allow derivative works (clips)",
                policy_id=policy.id,
            )

    def validate_for_clip_production(
        self,
        policy: "SourcePolicy",
        *,
        target_platform: str | None = None,
        clip_duration_seconds: float | None = None,
        is_commercial: bool = False,
        is_monetized: bool = False,
        attribution_acknowledged: bool = False,
        source_created_at: datetime | None = None,
    ) -> None:
        """Validate policy for clip production (clip creation time).

        This performs full validation including platform restrictions,
        duration limits, embargo enforcement, and attribution requirements.

        Args:
            policy: The SourcePolicy to validate against
            target_platform: Target platform for the clip (e.g., "youtube", "tiktok")
            clip_duration_seconds: Duration of the clip to create
            is_commercial: Whether the clip will be used for commercial purposes
            is_monetized: Whether the clip will be monetized (ads, sponsorships)
            attribution_acknowledged: Whether caller has acknowledged attribution requirement
            source_created_at: Creation timestamp of the source (for embargo calculation)

        Raises:
            PolicyViolationError: If any policy constraint is violated
        """
        # First, run source admission checks
        self.validate_for_source_admission(policy)

        # Check commercial use restriction
        if is_commercial and not policy.commercial_use_allowed:
            raise PolicyViolationError(
                f"Policy {policy.id} does not allow commercial use",
                policy_id=policy.id,
            )

        # Check monetization restriction (distinct from commercial)
        if is_monetized and not policy.monetization_allowed:
            raise PolicyViolationError(
                f"Policy {policy.id} does not allow monetized content",
                policy_id=policy.id,
            )

        # Check platform restriction
        # allowed_platforms is a list of allowed platforms
        # Empty list or None means all platforms allowed
        if target_platform and policy.allowed_platforms:
            if target_platform not in policy.allowed_platforms:
                raise PolicyViolationError(
                    f"Policy {policy.id} does not allow platform '{target_platform}'. "
                    f"Allowed: {policy.allowed_platforms}",
                    policy_id=policy.id,
                )

        # Check duration limit
        if (
            clip_duration_seconds is not None
            and policy.max_clip_duration_seconds is not None
            and clip_duration_seconds > policy.max_clip_duration_seconds
        ):
            raise PolicyViolationError(
                f"Policy {policy.id} limits clips to {policy.max_clip_duration_seconds}s, "
                f"requested {clip_duration_seconds:.1f}s",
                policy_id=policy.id,
            )

        # Check embargo (fail-closed: require source context if embargo is set)
        if policy.embargo_seconds > 0:
            if source_created_at is None:
                # Fail-closed: cannot verify embargo without source context
                raise PolicyViolationError(
                    f"Policy {policy.id} has embargo of {policy.embargo_seconds}s, "
                    "but source creation time is unknown - cannot verify embargo status",
                    policy_id=policy.id,
                )

            # Calculate embargo deadline
            embargo_deadline = source_created_at.timestamp() + policy.embargo_seconds
            now = datetime.now(UTC).timestamp()

            if now < embargo_deadline:
                embargo_end = datetime.fromtimestamp(embargo_deadline, UTC)
                raise PolicyViolationError(
                    f"Policy {policy.id} has active embargo until {embargo_end.isoformat()}, "
                    f"current time is {datetime.now(UTC).isoformat()}",
                    policy_id=policy.id,
                )

        # Check attribution acknowledgment
        if policy.attribution_required and not attribution_acknowledged:
            raise PolicyViolationError(
                f"Policy {policy.id} requires attribution, but attribution_acknowledged=False",
                policy_id=policy.id,
            )

    # Backwards compatibility alias
    def validate_for_clip_creation(
        self,
        policy: "SourcePolicy",
        *,
        target_platform: str | None = None,
        clip_duration_seconds: float | None = None,
        is_commercial: bool = False,
        is_monetized: bool = False,
        attribution_acknowledged: bool = False,
        source_created_at: datetime | None = None,
    ) -> None:
        """Deprecated: Use validate_for_clip_production instead."""
        self.validate_for_clip_production(
            policy,
            target_platform=target_platform,
            clip_duration_seconds=clip_duration_seconds,
            is_commercial=is_commercial,
            is_monetized=is_monetized,
            attribution_acknowledged=attribution_acknowledged,
            source_created_at=source_created_at,
        )

    def can_use_for_clips(
        self,
        policy: "SourcePolicy",
        *,
        target_platform: str | None = None,
        clip_duration_seconds: float | None = None,
        is_commercial: bool = False,
        is_monetized: bool = False,
        attribution_acknowledged: bool = False,
        source_created_at: datetime | None = None,
    ) -> tuple[bool, str | None]:
        """Check if policy allows clip creation, returning result and reason.

        Non-throwing variant of validate_for_clip_production for conditional checks.

        Returns:
            Tuple of (is_allowed, reason_if_denied)
        """
        try:
            self.validate_for_clip_production(
                policy,
                target_platform=target_platform,
                clip_duration_seconds=clip_duration_seconds,
                is_commercial=is_commercial,
                is_monetized=is_monetized,
                attribution_acknowledged=attribution_acknowledged,
                source_created_at=source_created_at,
            )
            return True, None
        except PolicyViolationError as e:
            return False, e.reason


__all__ = ["PolicyEligibilityService", "PolicyViolationError"]
