"""Unit tests for ClipCompositionService V2.

Tests the composition creation, fingerprint computation, and strategy validation.
"""

import pytest
from uuid import uuid4
from unittest.mock import MagicMock, AsyncMock

from app.services.clip_composition_service import (
    ClipCompositionService,
    PlanNotReadyError,
    PlanNotFoundError,
    UnsupportedStrategyError,
)


class TestClipCompositionService:
    """Tests for ClipCompositionService."""

    @pytest.fixture
    def session(self):
        """Create a mock async session."""
        return MagicMock()

    @pytest.fixture
    def service(self, session):
        """Create a ClipCompositionService instance."""
        return ClipCompositionService(session)

    def test_supported_strategies(self, service):
        """Service should define supported strategies."""
        assert "USE_DIRECTLY" in service.SUPPORTED_STRATEGIES
        assert "TRIM" in service.SUPPORTED_STRATEGIES
        assert "ADD_CONTEXT" in service.SUPPORTED_STRATEGIES

    def test_unsupported_strategies(self, service):
        """Service should define unsupported strategies."""
        assert "REAUTHOR" in service.UNSUPPORTED_STRATEGIES

    def test_rejected_strategies(self, service):
        """Service should define rejected strategies."""
        assert "REJECT" in service.REJECTED_STRATEGIES

    def test_valid_statuses(self, service):
        """Service should define valid statuses."""
        assert "pending" in service.VALID_STATUSES
        assert "validating" in service.VALID_STATUSES
        assert "ready" in service.VALID_STATUSES
        assert "rendering" in service.VALID_STATUSES
        assert "completed" in service.VALID_STATUSES
        assert "failed" in service.VALID_STATUSES


class TestFingerprintComputation:
    """Tests for composition fingerprint computation."""

    @pytest.fixture
    def service(self):
        """Create a ClipCompositionService instance."""
        return ClipCompositionService(MagicMock())

    def test_fingerprint_is_deterministic(self, service):
        """Same inputs should produce same fingerprint."""
        plan_id = uuid4()
        strategy = "TRIM"
        start = 10.0
        end = 30.0
        render_profile = "vertical_short_v1"
        audio_mode = "original"
        caption_mode = "none"

        fp1 = service._compute_fingerprint(
            plan_id, strategy, start, end, render_profile, audio_mode, caption_mode
        )
        fp2 = service._compute_fingerprint(
            plan_id, strategy, start, end, render_profile, audio_mode, caption_mode
        )

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex digest

    def test_fingerprint_differs_on_audio_mode(self, service):
        """Different audio_mode should produce different fingerprint."""
        plan_id = uuid4()
        strategy = "TRIM"
        start = 10.0
        end = 30.0
        render_profile = "vertical_short_v1"

        fp_original = service._compute_fingerprint(
            plan_id, strategy, start, end, render_profile, "original", "none"
        )
        fp_mixed = service._compute_fingerprint(
            plan_id, strategy, start, end, render_profile, "mixed", "none"
        )

        assert fp_original != fp_mixed

    def test_fingerprint_differs_on_caption_mode(self, service):
        """Different caption_mode should produce different fingerprint."""
        plan_id = uuid4()
        strategy = "TRIM"
        start = 10.0
        end = 30.0
        render_profile = "vertical_short_v1"
        audio_mode = "original"

        fp_none = service._compute_fingerprint(
            plan_id, strategy, start, end, render_profile, audio_mode, "none"
        )
        fp_burned = service._compute_fingerprint(
            plan_id, strategy, start, end, render_profile, audio_mode, "burned"
        )

        assert fp_none != fp_burned

    def test_fingerprint_differs_on_render_profile(self, service):
        """Different render_profile should produce different fingerprint."""
        plan_id = uuid4()
        strategy = "TRIM"
        start = 10.0
        end = 30.0

        fp_v1 = service._compute_fingerprint(
            plan_id, strategy, start, end, "vertical_short_v1", "original", "none"
        )
        fp_v2 = service._compute_fingerprint(
            plan_id, strategy, start, end, "vertical_short_v2", "original", "none"
        )

        assert fp_v1 != fp_v2


class TestCreateCompositionFromPlan:
    """Tests for create_composition_from_plan method."""

    @pytest.fixture
    def session(self):
        """Create a mock async session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        return session

    @pytest.fixture
    def service(self, session):
        """Create a ClipCompositionService instance."""
        return ClipCompositionService(session)

    @pytest.mark.asyncio
    async def test_plan_not_found_raises_error(self, service, session):
        """Non-existent plan should raise PlanNotFoundError."""
        from sqlalchemy.engine import Result

        result = MagicMock(spec=Result)
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(PlanNotFoundError):
            await service.create_composition_from_plan(uuid4())

    @pytest.mark.asyncio
    async def test_plan_not_ready_raises_error(self, service, session):
        """Plan not in 'ready' status should raise PlanNotReadyError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "draft"
        plan.strategy = "TRIM"

        result = MagicMock(spec=Result)
        result.scalar_one_or_none.return_value = plan
        session.execute.return_value = result

        with pytest.raises(PlanNotReadyError):
            await service.create_composition_from_plan(uuid4())

    @pytest.mark.asyncio
    async def test_reject_strategy_raises_error(self, service, session):
        """REJECT strategy should raise UnsupportedStrategyError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "REJECT"

        result = MagicMock(spec=Result)
        result.scalar_one_or_none.return_value = plan
        session.execute.return_value = result

        with pytest.raises(UnsupportedStrategyError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "rejected" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_reauthor_strategy_raises_error(self, service, session):
        """REAUTHOR strategy should raise UnsupportedStrategyError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "REAUTHOR"

        result = MagicMock(spec=Result)
        result.scalar_one_or_none.return_value = plan
        session.execute.return_value = result

        with pytest.raises(UnsupportedStrategyError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "not yet implemented" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_existing_composition_returns_existing(self, service, session):
        """Existing composition with same fingerprint should be returned (idempotency)."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan, ClipComposition

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.id = uuid4()
        plan.source_start_seconds = 10.0
        plan.source_end_seconds = 60.0
        plan.analysis_id = None

        existing_composition = MagicMock(spec=ClipComposition)
        existing_composition.id = uuid4()

        # First call returns plan, second returns existing composition (fingerprint match)
        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = existing_composition
        session.execute.side_effect = results

        # Should return existing composition, not raise error (fingerprint-based idempotency)
        result = await service.create_composition_from_plan(uuid4())
        assert result is existing_composition


class TestUpdateStatus:
    """Tests for update_status method."""

    @pytest.fixture
    def session(self):
        """Create a mock async session."""
        session = MagicMock()
        session.execute = AsyncMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        return session

    @pytest.fixture
    def service(self, session):
        """Create a ClipCompositionService instance."""
        return ClipCompositionService(session)

    @pytest.mark.asyncio
    async def test_invalid_status_raises_error(self, service):
        """Invalid status should raise CompositionError."""
        with pytest.raises(Exception) as exc_info:
            await service.update_status(uuid4(), "invalid_status")

        assert "Invalid status" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_composition_not_found_raises_error(self, service, session):
        """Non-existent composition should raise CompositionError."""
        from sqlalchemy.engine import Result

        result = MagicMock(spec=Result)
        result.scalar_one_or_none.return_value = None
        session.execute.return_value = result

        with pytest.raises(Exception) as exc_info:
            await service.update_status(uuid4(), "rendering")

        assert "not found" in str(exc_info.value)
