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
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id = uuid4()
        analysis_id = uuid4()
        plan_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()
        source_sha256 = "abc123def456"
        start = 10.0
        end = 30.0
        strategy = "TRIM"
        render_profile = "vertical_short_v1"
        audio_mode = "original"
        caption_mode = "none"
        contract_version = "clip_composition_v2"

        fp1 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, audio_mode, caption_mode, contract_version
        )
        fp2 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, audio_mode, caption_mode, contract_version
        )

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex digest

    def test_fingerprint_differs_on_audio_mode(self, service):
        """Different audio_mode should produce different fingerprint."""
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id = uuid4()
        analysis_id = uuid4()
        plan_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()
        source_sha256 = "abc123def456"
        start = 10.0
        end = 30.0
        strategy = "TRIM"
        render_profile = "vertical_short_v1"
        contract_version = "clip_composition_v2"

        fp_original = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, "original", "none", contract_version
        )
        fp_mixed = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, "mixed", "none", contract_version
        )

        assert fp_original != fp_mixed

    def test_fingerprint_differs_on_caption_mode(self, service):
        """Different caption_mode should produce different fingerprint."""
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id = uuid4()
        analysis_id = uuid4()
        plan_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()
        source_sha256 = "abc123def456"
        start = 10.0
        end = 30.0
        strategy = "TRIM"
        render_profile = "vertical_short_v1"
        audio_mode = "original"
        contract_version = "clip_composition_v2"

        fp_none = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, audio_mode, "none", contract_version
        )
        fp_burned = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, audio_mode, "burned", contract_version
        )

        assert fp_none != fp_burned

    def test_fingerprint_differs_on_render_profile(self, service):
        """Different render_profile should produce different fingerprint."""
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id = uuid4()
        analysis_id = uuid4()
        plan_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()
        source_sha256 = "abc123def456"
        start = 10.0
        end = 30.0
        strategy = "TRIM"
        audio_mode = "original"
        caption_mode = "none"
        contract_version = "clip_composition_v2"

        fp_v1 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, "vertical_short_v1", audio_mode, caption_mode, contract_version
        )
        fp_v2 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, "vertical_short_v2", audio_mode, caption_mode, contract_version
        )

        assert fp_v1 != fp_v2

    def test_fingerprint_differs_on_provenance(self, service):
        """Different provenance (source_sha256) should produce different fingerprint."""
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id = uuid4()
        analysis_id = uuid4()
        plan_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()
        start = 10.0
        end = 30.0
        strategy = "TRIM"
        render_profile = "vertical_short_v1"
        audio_mode = "original"
        caption_mode = "none"
        contract_version = "clip_composition_v2"

        fp_sha1 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, "sha256_abc123", start, end,
            strategy, render_profile, audio_mode, caption_mode, contract_version
        )
        fp_sha2 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id, analysis_id, plan_id,
            media_id, transcription_id, "sha256_xyz789", start, end,
            strategy, render_profile, audio_mode, caption_mode, contract_version
        )

        assert fp_sha1 != fp_sha2

    def test_fingerprint_differs_on_lineage(self, service):
        """Different candidate_id should produce different fingerprint."""
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id_1 = uuid4()
        candidate_id_2 = uuid4()
        analysis_id = uuid4()
        plan_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()
        source_sha256 = "abc123def456"
        start = 10.0
        end = 30.0
        strategy = "TRIM"
        render_profile = "vertical_short_v1"
        audio_mode = "original"
        caption_mode = "none"
        contract_version = "clip_composition_v2"

        fp_c1 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id_1, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, audio_mode, caption_mode, contract_version
        )
        fp_c2 = service._compute_fingerprint(
            workflow_id, source_id, candidate_id_2, analysis_id, plan_id,
            media_id, transcription_id, source_sha256, start, end,
            strategy, render_profile, audio_mode, caption_mode, contract_version
        )

        assert fp_c1 != fp_c2


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
        from app.models.entities import ShortEditorialPlan, ClipComposition, ClipSource

        # Create real UUIDs for lineage
        plan_id = uuid4()
        workflow_id = uuid4()
        source_id = uuid4()
        candidate_id = uuid4()
        media_id = uuid4()
        transcription_id = uuid4()

        # Mock plan with all required lineage fields
        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.id = plan_id
        plan.workflow_id = workflow_id
        plan.source_id = source_id
        plan.candidate_id = candidate_id
        plan.analysis_id = None
        plan.source_start_seconds = 10.0
        plan.source_end_seconds = 60.0
        plan.duration_seconds = 50.0
        plan.source_start_segment_id = None
        plan.source_end_segment_id = None

        # Mock source with required lineage fields
        source = MagicMock(spec=ClipSource)
        source.id = source_id
        source.media_id = media_id
        source.transcription_id = transcription_id
        source.source_sha256 = "abc123def456"

        existing_composition = MagicMock(spec=ClipComposition)
        existing_composition.id = uuid4()

        # First call returns plan, second returns source, third returns existing composition
        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = source
        results[2].scalar_one_or_none.return_value = existing_composition
        session.execute.side_effect = results

        # Should return existing composition, not raise error (fingerprint-based idempotency)
        result = await service.create_composition_from_plan(uuid4())
        assert result is existing_composition


class TestLineageValidation:
    """Tests for lineage validation in create_composition_from_plan."""

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
    async def test_plan_without_source_id_raises_error(self, service, session):
        """Plan without source_id should raise IncompleteLineageError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan
        from app.services.clip_composition_service import IncompleteLineageError

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.source_id = None

        result = MagicMock(spec=Result)
        result.scalar_one_or_none.return_value = plan
        session.execute.return_value = result

        with pytest.raises(IncompleteLineageError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "no source_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_source_not_found_raises_error(self, service, session):
        """Missing ClipSource should raise IncompleteLineageError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan
        from app.services.clip_composition_service import IncompleteLineageError

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.source_id = uuid4()

        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = None  # Source not found
        session.execute.side_effect = results

        with pytest.raises(IncompleteLineageError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "not found" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_source_without_media_id_raises_error(self, service, session):
        """ClipSource without media_id should raise IncompleteLineageError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan, ClipSource
        from app.services.clip_composition_service import IncompleteLineageError

        source_id = uuid4()

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.source_id = source_id

        source = MagicMock(spec=ClipSource)
        source.id = source_id
        source.media_id = None  # Missing media_id

        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = source
        session.execute.side_effect = results

        with pytest.raises(IncompleteLineageError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "no media_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_source_without_transcription_id_raises_error(self, service, session):
        """ClipSource without transcription_id should raise IncompleteLineageError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan, ClipSource
        from app.services.clip_composition_service import IncompleteLineageError

        source_id = uuid4()

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.source_id = source_id

        source = MagicMock(spec=ClipSource)
        source.id = source_id
        source.media_id = uuid4()
        source.transcription_id = None  # Missing transcription_id

        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = source
        session.execute.side_effect = results

        with pytest.raises(IncompleteLineageError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "no transcription_id" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_source_without_source_sha256_raises_error(self, service, session):
        """ClipSource without source_sha256 should raise IncompleteLineageError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan, ClipSource
        from app.services.clip_composition_service import IncompleteLineageError

        source_id = uuid4()

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.source_id = source_id

        source = MagicMock(spec=ClipSource)
        source.id = source_id
        source.media_id = uuid4()
        source.transcription_id = uuid4()
        source.source_sha256 = None  # Missing source_sha256

        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = source
        session.execute.side_effect = results

        with pytest.raises(IncompleteLineageError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "no source_sha256" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_lineage_mismatch_raises_error(self, service, session):
        """Mismatch between plan.candidate_id and analysis.candidate_id should raise LineageMismatchError."""
        from sqlalchemy.engine import Result
        from app.models.entities import ShortEditorialPlan, ClipSource, EditorialSuitabilityAnalysis
        from app.services.clip_composition_service import LineageMismatchError

        source_id = uuid4()
        plan_candidate_id = uuid4()
        analysis_candidate_id = uuid4()  # Different candidate

        plan = MagicMock(spec=ShortEditorialPlan)
        plan.status = "ready"
        plan.strategy = "TRIM"
        plan.source_id = source_id
        plan.candidate_id = plan_candidate_id
        plan.analysis_id = uuid4()
        plan.workflow_id = uuid4()
        plan.source_start_seconds = 10.0
        plan.source_end_seconds = 60.0
        plan.duration_seconds = 50.0

        source = MagicMock(spec=ClipSource)
        source.id = source_id
        source.media_id = uuid4()
        source.transcription_id = uuid4()
        source.source_sha256 = "abc123"

        analysis = MagicMock(spec=EditorialSuitabilityAnalysis)
        analysis.candidate_id = analysis_candidate_id  # Mismatch!

        results = [
            MagicMock(spec=Result),
            MagicMock(spec=Result),
            MagicMock(spec=Result),
        ]
        results[0].scalar_one_or_none.return_value = plan
        results[1].scalar_one_or_none.return_value = source
        results[2].scalar_one_or_none.return_value = analysis
        session.execute.side_effect = results

        with pytest.raises(LineageMismatchError) as exc_info:
            await service.create_composition_from_plan(uuid4())

        assert "does not match" in str(exc_info.value).lower()


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
