"""Unit tests for PolicyEligibilityService."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.services.policy_eligibility_service import (
    PolicyEligibilityService,
    PolicyViolationError,
)


class MockPolicy:
    """Mock SourcePolicy for testing."""

    def __init__(
        self,
        *,
        id: UUID | None = None,
        verification_status: str = "verified",
        derivatives_allowed: bool = True,
        commercial_use_allowed: bool = False,
        monetization_allowed: bool = False,
        allowed_platforms: list[str] | None = None,
        max_clip_duration_seconds: int | None = None,
        embargo_seconds: int = 0,
        attribution_required: bool = False,
    ):
        self.id = id or uuid4()
        self.verification_status = verification_status
        self.derivatives_allowed = derivatives_allowed
        self.commercial_use_allowed = commercial_use_allowed
        self.monetization_allowed = monetization_allowed
        self.allowed_platforms = allowed_platforms
        self.max_clip_duration_seconds = max_clip_duration_seconds
        self.embargo_seconds = embargo_seconds
        self.attribution_required = attribution_required


class TestValidateForSourceAdmission:
    """Tests for validate_for_source_admission."""

    def test_verified_policy_with_derivatives_allowed(self):
        """Verified policy with derivatives_allowed passes admission."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
        )
        service = PolicyEligibilityService()
        # Should not raise
        service.validate_for_source_admission(policy)

    def test_unverified_policy_rejected(self):
        """Unverified policy is rejected at admission."""
        policy = MockPolicy(
            verification_status="unverified",
            derivatives_allowed=True,
        )
        service = PolicyEligibilityService()
        with pytest.raises(PolicyViolationError, match="not verified"):
            service.validate_for_source_admission(policy)

    def test_blocked_policy_rejected(self):
        """Blocked policy is rejected at admission."""
        policy = MockPolicy(
            verification_status="blocked",
            derivatives_allowed=True,
        )
        service = PolicyEligibilityService()
        with pytest.raises(PolicyViolationError, match="blocked"):
            service.validate_for_source_admission(policy)

    def test_derivatives_not_allowed_rejected(self):
        """Policy without derivatives_allowed is rejected."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=False,
        )
        service = PolicyEligibilityService()
        with pytest.raises(PolicyViolationError, match="does not allow derivative works"):
            service.validate_for_source_admission(policy)


class TestValidateForClipProduction:
    """Tests for validate_for_clip_production."""

    def test_basic_clip_production_passes(self):
        """Basic clip production with valid policy passes."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
        )
        service = PolicyEligibilityService()
        service.validate_for_clip_production(
            policy,
            source_created_at=datetime.now(UTC) - timedelta(days=1),
        )

    def test_commercial_use_rejected_when_not_allowed(self):
        """Commercial use is rejected when policy doesn't allow it."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            commercial_use_allowed=False,
        )
        service = PolicyEligibilityService()
        with pytest.raises(PolicyViolationError, match="does not allow commercial use"):
            service.validate_for_clip_production(
                policy,
                is_commercial=True,
                source_created_at=datetime.now(UTC),
            )

    def test_monetization_rejected_when_not_allowed(self):
        """Monetization is rejected when policy doesn't allow it."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            monetization_allowed=False,
        )
        service = PolicyEligibilityService()
        with pytest.raises(PolicyViolationError, match="does not allow monetized"):
            service.validate_for_clip_production(
                policy,
                is_monetized=True,
                source_created_at=datetime.now(UTC),
            )

    def test_platform_restriction_enforced(self):
        """Platform restriction is enforced."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            allowed_platforms=["youtube", "tiktok"],
        )
        service = PolicyEligibilityService()
        # Allowed platform passes
        service.validate_for_clip_production(
            policy,
            target_platform="youtube",
            source_created_at=datetime.now(UTC),
        )
        # Disallowed platform rejected
        with pytest.raises(PolicyViolationError, match="does not allow platform"):
            service.validate_for_clip_production(
                policy,
                target_platform="instagram",
                source_created_at=datetime.now(UTC),
            )

    def test_duration_limit_enforced(self):
        """Duration limit is enforced."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            max_clip_duration_seconds=60,
        )
        service = PolicyEligibilityService()
        # Within limit passes
        service.validate_for_clip_production(
            policy,
            clip_duration_seconds=30.0,
            source_created_at=datetime.now(UTC),
        )
        # Exceeds limit rejected
        with pytest.raises(PolicyViolationError, match="limits clips to"):
            service.validate_for_clip_production(
                policy,
                clip_duration_seconds=90.0,
                source_created_at=datetime.now(UTC),
            )

    def test_embargo_active_rejected(self):
        """Active embargo is rejected (fail-closed)."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            embargo_seconds=86400,  # 24 hours
        )
        service = PolicyEligibilityService()
        # Source created 1 hour ago - embargo still active
        with pytest.raises(PolicyViolationError, match="active embargo"):
            service.validate_for_clip_production(
                policy,
                source_created_at=datetime.now(UTC) - timedelta(hours=1),
            )

    def test_embargo_expired_passes(self):
        """Expired embargo passes."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            embargo_seconds=3600,  # 1 hour
        )
        service = PolicyEligibilityService()
        # Source created 2 hours ago - embargo expired
        service.validate_for_clip_production(
            policy,
            source_created_at=datetime.now(UTC) - timedelta(hours=2),
        )

    def test_embargo_unknown_source_time_rejected(self):
        """Embargo check with unknown source time is rejected (fail-closed)."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            embargo_seconds=3600,
        )
        service = PolicyEligibilityService()
        # source_created_at=None - cannot verify embargo
        with pytest.raises(PolicyViolationError, match="cannot verify embargo"):
            service.validate_for_clip_production(
                policy,
                source_created_at=None,
            )

    def test_attribution_required_enforced(self):
        """Attribution requirement is enforced."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            attribution_required=True,
        )
        service = PolicyEligibilityService()
        # Without attribution acknowledgment
        with pytest.raises(PolicyViolationError, match="requires attribution"):
            service.validate_for_clip_production(
                policy,
                attribution_acknowledged=False,
                source_created_at=datetime.now(UTC),
            )
        # With attribution acknowledgment
        service.validate_for_clip_production(
            policy,
            attribution_acknowledged=True,
            source_created_at=datetime.now(UTC),
        )

    def test_zero_embargo_passes(self):
        """Zero embargo (no restriction) passes immediately."""
        policy = MockPolicy(
            verification_status="verified",
            derivatives_allowed=True,
            embargo_seconds=0,
        )
        service = PolicyEligibilityService()
        # Just created - should pass with zero embargo
        service.validate_for_clip_production(
            policy,
            source_created_at=datetime.now(UTC),
        )
