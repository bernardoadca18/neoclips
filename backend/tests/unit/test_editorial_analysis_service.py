"""Unit tests for EditorialAnalysisService."""

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    ClipCandidate,
    ClipSource,
    ClipWorkflow,
    DiscoveryRun,
    EditorialSuitabilityAnalysis,
)
from app.services.editorial_analysis_service import (
    EditorialAnalysisService,
    EditorialAnalysisError,
    CandidateNotReadyError,
)
from app.services.ninerouter_editorial_provider import (
    CandidateContext,
    LLMEditorialAnalysisResponse,
    NineRouterEditorialProvider,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_context_service() -> AsyncMock:
    """Create a mock candidate context service."""
    service = AsyncMock()
    service.get_candidate_context = AsyncMock(return_value={
        "candidate_id": str(uuid4()),
        "candidate_segments": [],
        "context_before_segments": [],
        "context_after_segments": [],
        "transcription_id": str(uuid4()),
        "source_id": str(uuid4()),
    })
    service.get_segments_for_analysis = AsyncMock(return_value=([], [], []))
    return service


@pytest.fixture
def mock_editorial_provider() -> MagicMock:
    """Create a mock editorial provider."""
    provider = MagicMock(spec=NineRouterEditorialProvider)
    provider.combo = "neoclips-editorial"
    provider._get_prompt_hash = MagicMock(return_value="abc123")

    llm_response = LLMEditorialAnalysisResponse(
        standalone_score=85,
        context_dependency="low",
        hook_strength=90,
        payoff_strength=75,
        ending_completeness=80,
        reference_dependency_level="none",
        reference_dependency_examples=[],
        recommended_strategy="USE_DIRECTLY",
        recommended_start_segment_id=None,
        recommended_end_segment_id=None,
        analysis_summary="This clip is suitable for direct use.",
    )

    provider.analyze_candidate = AsyncMock(return_value=(llm_response, "{}"))
    return provider


@pytest.fixture
def sample_candidate() -> ClipCandidate:
    """Create a sample clip candidate."""
    return ClipCandidate(
        id=uuid4(),
        run_id=uuid4(),
        canonical_start_seconds=100.0,
        canonical_end_seconds=160.0,
        duration_seconds=60.0,
        title="Test Candidate",
        summary="A test candidate for analysis",
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
        prompt_hash="abc123",
        config_snapshot=json.dumps({"context_before_seconds": 45.0, "context_after_seconds": 40.0}),
        request_fingerprint="test_fingerprint",
        requested_combo="neoclips-editorial",
        context_before_seconds=45.0,
        context_after_seconds=40.0,
        status="pending",
        attempt_count=0,
    )


class TestEditorialAnalysisServiceInit:
    """Tests for service initialization."""

    def test_init_with_provider(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
    ) -> None:
        """Test initialization with custom provider."""
        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        assert service.session is mock_session
        assert service.context_service is mock_context_service
        assert service.editorial_provider is mock_editorial_provider

    def test_init_without_provider(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
    ) -> None:
        """Test initialization without provider creates default."""
        with patch(
            "app.services.editorial_analysis_service.NineRouterEditorialProvider"
        ) as mock_provider_class:
            service = EditorialAnalysisService(
                session=mock_session,
                context_service=mock_context_service,
            )

            mock_provider_class.assert_called_once()
            assert service.session is mock_session


class TestComputeRequestFingerprint:
    """Tests for fingerprint computation."""

    def test_fingerprint_deterministic(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
    ) -> None:
        """Test that fingerprint is deterministic."""
        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
        )

        candidate_id = uuid4()
        fingerprint1 = service._compute_request_fingerprint(
            candidate_id, 45.0, 40.0, "abc123"
        )
        fingerprint2 = service._compute_request_fingerprint(
            candidate_id, 45.0, 40.0, "abc123"
        )

        assert fingerprint1 == fingerprint2
        assert len(fingerprint1) == 64  # SHA-256 hex digest

    def test_fingerprint_different_inputs(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
    ) -> None:
        """Test that different inputs produce different fingerprints."""
        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
        )

        candidate_id = uuid4()
        fingerprint1 = service._compute_request_fingerprint(
            candidate_id, 45.0, 40.0, "abc123"
        )
        fingerprint2 = service._compute_request_fingerprint(
            candidate_id, 50.0, 40.0, "abc123"
        )

        assert fingerprint1 != fingerprint2


class TestGetOrCreateAnalysis:
    """Tests for get_or_create_analysis."""

    @pytest.mark.asyncio
    async def test_creates_new_analysis(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
        sample_candidate: ClipCandidate,
    ) -> None:
        """Test creating a new analysis."""
        # First call: get candidate (returns candidate); second call: check existing (None)
        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = sample_candidate
            else:
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        analysis = await service.get_or_create_analysis(
            candidate_id=sample_candidate.id,
        )

        assert analysis is not None
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_duplicate_candidate(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
    ) -> None:
        """Test that duplicate candidates are rejected."""
        duplicate_candidate = ClipCandidate(
            id=uuid4(),
            run_id=uuid4(),
            canonical_start_seconds=100.0,
            canonical_end_seconds=160.0,
            duration_seconds=60.0,
            is_duplicate=True,
        )

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = duplicate_candidate
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        with pytest.raises(CandidateNotReadyError) as exc_info:
            await service.get_or_create_analysis(candidate_id=duplicate_candidate.id)

        assert "marked as duplicate" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_candidate(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
    ) -> None:
        """Test that missing candidates raise error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        with pytest.raises(CandidateNotReadyError) as exc_info:
            await service.get_or_create_analysis(candidate_id=uuid4())

        assert "not found" in str(exc_info.value)


class TestExecuteAnalysis:
    """Tests for execute_analysis."""

    @pytest.mark.asyncio
    async def test_executes_analysis_successfully(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
        sample_analysis: EditorialSuitabilityAnalysis,
    ) -> None:
        """Test successful analysis execution."""
        sample_analysis.status = "pending"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_analysis
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        result = await service.execute_analysis(sample_analysis.id)

        assert result.status == "completed"
        assert result.standalone_score == 85
        assert result.recommended_strategy == "USE_DIRECTLY"
        mock_session.commit.assert_called()

    @pytest.mark.asyncio
    async def test_skips_already_completed(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
        sample_analysis: EditorialSuitabilityAnalysis,
    ) -> None:
        """Test that completed analyses are skipped."""
        sample_analysis.status = "completed"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_analysis
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        result = await service.execute_analysis(sample_analysis.id)

        assert result.status == "completed"
        mock_editorial_provider.analyze_candidate.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_processing_status(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
        sample_analysis: EditorialSuitabilityAnalysis,
    ) -> None:
        """Test that processing analyses are returned as-is."""
        sample_analysis.status = "processing"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_analysis
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        result = await service.execute_analysis(sample_analysis.id)

        assert result.status == "processing"
        mock_editorial_provider.analyze_candidate.assert_not_called()


class TestGetAnalysisByCandidate:
    """Tests for get_analysis_by_candidate."""

    @pytest.mark.asyncio
    async def test_returns_analysis(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
        sample_analysis: EditorialSuitabilityAnalysis,
    ) -> None:
        """Test retrieving analysis by candidate."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_analysis
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        result = await service.get_analysis_by_candidate(sample_analysis.candidate_id)

        assert result == sample_analysis

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(
        self,
        mock_session: AsyncMock,
        mock_context_service: AsyncMock,
        mock_editorial_provider: MagicMock,
    ) -> None:
        """Test returning None when no analysis exists."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = EditorialAnalysisService(
            session=mock_session,
            context_service=mock_context_service,
            editorial_provider=mock_editorial_provider,
        )

        result = await service.get_analysis_by_candidate(uuid4())

        assert result is None
