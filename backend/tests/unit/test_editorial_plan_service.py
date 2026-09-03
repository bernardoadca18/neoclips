"""Unit tests for EditorialPlanService."""

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    ClipCandidate,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    EditorialSuitabilityAnalysis,
    ShortEditorialPlan,
)
from app.services.editorial_plan_service import (
    EditorialPlanService,
    PlanError,
    CandidateNotFoundError,
    AnalysisNotFoundError,
    PlanAlreadyExistsError,
    InvalidStrategyError,
)


@pytest.fixture
def mock_media_indexer_client() -> AsyncMock:
    """Create a mock Media Indexer client."""
    client = AsyncMock()
    client.get_all_transcript_segments = AsyncMock(return_value=[])
    return client


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def sample_workflow() -> ClipWorkflow:
    """Create a sample workflow."""
    return ClipWorkflow(
        id=uuid4(),
        source_id=uuid4(),
        status="awaiting_selection",
        attempt_count=0,
    )


@pytest.fixture
def sample_run(sample_workflow: ClipWorkflow) -> DiscoveryRun:
    """Create a sample discovery run."""
    return DiscoveryRun(
        id=uuid4(),
        workflow_id=sample_workflow.id,
        status="completed",
        profile="default",
        total_windows=10,
        processed_windows=10,
        total_candidates=5,
    )


@pytest.fixture
def sample_candidate(sample_run: DiscoveryRun) -> ClipCandidate:
    """Create a sample clip candidate."""
    return ClipCandidate(
        id=uuid4(),
        run_id=sample_run.id,
        canonical_start_seconds=100.0,
        canonical_end_seconds=160.0,
        duration_seconds=60.0,
        title="Test Candidate",
        summary="A test candidate",
        hook_type="question",
        score_v1=85.0,
        discovery_rank=1,
        is_duplicate=False,
        selected=True,
    )


@pytest.fixture
def sample_analysis(sample_candidate: ClipCandidate) -> EditorialSuitabilityAnalysis:
    """Create a sample editorial analysis."""
    return EditorialSuitabilityAnalysis(
        id=uuid4(),
        candidate_id=sample_candidate.id,
        source_id=uuid4(),
        transcription_id=uuid4(),
        strategy_id="editorial_suitability",
        strategy_version="1.0.0",
        prompt_id="editorial_suitability_v1",
        prompt_version="1.0.0",
        status="completed",
        recommended_strategy="USE_DIRECTLY",
        recommended_start_segment_id=None,
        recommended_end_segment_id=None,
        config_snapshot=json.dumps({"context_before_seconds": 45.0}),
    )


@pytest.fixture
def sample_plan(sample_candidate: ClipCandidate, sample_workflow: ClipWorkflow) -> ShortEditorialPlan:
    """Create a sample editorial plan."""
    return ShortEditorialPlan(
        id=uuid4(),
        workflow_id=sample_workflow.id,
        source_id=sample_workflow.source_id,
        candidate_id=sample_candidate.id,
        analysis_id=None,
        strategy="USE_DIRECTLY",
        decision_source="model_recommendation",
        source_start_seconds=100.0,
        source_end_seconds=160.0,
        duration_seconds=60.0,
        status="draft",
        plan_version="1.0.0",
        fingerprint="test_fingerprint",
    )


class TestEditorialPlanServiceInit:
    """Tests for service initialization."""

    def test_init(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test service initialization."""
        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        assert service.session is mock_session
        assert service.PLAN_VERSION == "1.0.0"
        assert "USE_DIRECTLY" in service.VALID_STRATEGIES
        assert "REJECT" in service.VALID_STRATEGIES


class TestComputeFingerprint:
    """Tests for fingerprint computation."""

    def test_fingerprint_deterministic(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that fingerprint is deterministic."""
        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        candidate_id = uuid4()
        fp1 = service._compute_fingerprint(candidate_id, "USE_DIRECTLY", 100.0, 160.0)
        fp2 = service._compute_fingerprint(candidate_id, "USE_DIRECTLY", 100.0, 160.0)

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex digest

    def test_fingerprint_different_strategy(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that different strategies produce different fingerprints."""
        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        candidate_id = uuid4()
        fp1 = service._compute_fingerprint(candidate_id, "USE_DIRECTLY", 100.0, 160.0)
        fp2 = service._compute_fingerprint(candidate_id, "TRIM", 100.0, 160.0)

        assert fp1 != fp2


class TestCreatePlanFromAnalysis:
    """Tests for create_plan_from_analysis."""

    @pytest.mark.asyncio
    async def test_creates_plan(
        self,
        mock_session: AsyncMock,
        sample_analysis: EditorialSuitabilityAnalysis,
        sample_candidate: ClipCandidate,
        sample_run: DiscoveryRun,
        sample_workflow: ClipWorkflow,
    ) -> None:
        """Test creating a plan from analysis."""
        # Set up mock chain
        mock_result = MagicMock()

        def execute_side_effect(query):
            result = MagicMock()
            # First call: get analysis
            if hasattr(query, 'where') and 'editorial_suitability_analyses' in str(query):
                result.scalar_one_or_none.return_value = sample_analysis
            # Second call: get candidate
            elif 'clip_candidates' in str(query):
                result.scalar_one_or_none.return_value = sample_candidate
            # Third call: get run
            elif 'discovery_runs' in str(query):
                result.scalar_one_or_none.return_value = sample_run
            # Fourth call: get workflow
            elif 'clip_workflows' in str(query):
                result.scalar_one_or_none.return_value = sample_workflow
            # Fifth call: check existing plan
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        plan = await service.create_plan_from_analysis(sample_analysis.id)

        assert plan is not None
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_missing_analysis(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that missing analysis raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        with pytest.raises(AnalysisNotFoundError):
            await service.create_plan_from_analysis(uuid4())

    @pytest.mark.asyncio
    async def test_rejects_incomplete_analysis(
        self,
        mock_session: AsyncMock,
        sample_analysis: EditorialSuitabilityAnalysis,
    ) -> None:
        """Test that incomplete analysis raises error."""
        sample_analysis.status = "pending"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_analysis
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        with pytest.raises(PlanError) as exc_info:
            await service.create_plan_from_analysis(sample_analysis.id)

        assert "not completed" in str(exc_info.value)


class TestCreateManualPlan:
    """Tests for create_manual_plan."""

    @pytest.mark.asyncio
    async def test_creates_manual_plan(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
        sample_run: DiscoveryRun,
        sample_workflow: ClipWorkflow,
    ) -> None:
        """Test creating a manual plan."""
        def execute_side_effect(query):
            result = MagicMock()
            if 'clip_candidates' in str(query):
                result.scalar_one_or_none.return_value = sample_candidate
            elif 'discovery_runs' in str(query):
                result.scalar_one_or_none.return_value = sample_run
            elif 'clip_workflows' in str(query):
                result.scalar_one_or_none.return_value = sample_workflow
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        plan = await service.create_manual_plan(
            candidate_id=sample_candidate.id,
            strategy="TRIM",
            source_start_seconds=100.0,
            source_end_seconds=150.0,
        )

        assert plan is not None
        mock_session.add.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_strategy(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that invalid strategy raises error."""
        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        with pytest.raises(InvalidStrategyError):
            await service.create_manual_plan(
                candidate_id=uuid4(),
                strategy="INVALID_STRATEGY",
                source_start_seconds=100.0,
                source_end_seconds=160.0,
            )

    @pytest.mark.asyncio
    async def test_requires_rejection_reason(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that REJECT strategy requires reason."""
        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        with pytest.raises(PlanError) as exc_info:
            await service.create_manual_plan(
                candidate_id=uuid4(),
                strategy="REJECT",
                source_start_seconds=100.0,
                source_end_seconds=160.0,
                rejection_reason=None,
            )

        assert "rejection_reason is required" in str(exc_info.value)


class TestUpdatePlanStatus:
    """Tests for update_plan_status."""

    @pytest.mark.asyncio
    async def test_updates_status(
        self,
        mock_session: AsyncMock,
        sample_plan: ShortEditorialPlan,
    ) -> None:
        """Test updating plan status."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_plan
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        result = await service.update_plan_status(sample_plan.id, "ready")

        assert result.status == "ready"
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_status(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that invalid status raises error."""
        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        with pytest.raises(PlanError):
            await service.update_plan_status(uuid4(), "invalid_status")

    @pytest.mark.asyncio
    async def test_rejects_missing_plan(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test that missing plan raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)

        with pytest.raises(PlanError) as exc_info:
            await service.update_plan_status(uuid4(), "ready")

        assert "not found" in str(exc_info.value)


class TestGetPlanByCandidate:
    """Tests for get_plan_by_candidate."""

    @pytest.mark.asyncio
    async def test_returns_plan(
        self,
        mock_session: AsyncMock,
        sample_plan: ShortEditorialPlan,
    ) -> None:
        """Test retrieving plan by candidate."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_plan
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        result = await service.get_plan_by_candidate(sample_plan.candidate_id)

        assert result == sample_plan

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test returning None when no plan exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        result = await service.get_plan_by_candidate(uuid4())

        assert result is None


class TestGetPlansByWorkflow:
    """Tests for get_plans_by_workflow."""

    @pytest.mark.asyncio
    async def test_returns_plans(
        self,
        mock_session: AsyncMock,
        sample_plan: ShortEditorialPlan,
    ) -> None:
        """Test retrieving plans by workflow."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [sample_plan]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        result = await service.get_plans_by_workflow(sample_plan.workflow_id)

        assert len(result) == 1
        assert result[0] == sample_plan

    @pytest.mark.asyncio
    async def test_returns_empty_list(self, mock_session: AsyncMock, mock_media_indexer_client: AsyncMock) -> None:
        """Test returning empty list when no plans exist."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        service = EditorialPlanService(mock_session, mock_media_indexer_client)
        result = await service.get_plans_by_workflow(uuid4())

        assert result == []
