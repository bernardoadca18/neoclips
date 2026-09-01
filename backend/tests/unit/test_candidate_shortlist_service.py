"""Unit tests for CandidateShortlistService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipCandidate, DiscoveryRun
from app.services.candidate_shortlist_service import (
    CandidateShortlistService,
    ShortlistError,
    RunNotFoundError,
    RunNotTerminalError,
)


@pytest.fixture
def mock_session() -> AsyncMock:
    """Create a mock async session."""
    session = AsyncMock(spec=AsyncSession)
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    return session


@pytest.fixture
def sample_run() -> DiscoveryRun:
    """Create a sample discovery run in terminal state."""
    return DiscoveryRun(
        id=uuid4(),
        workflow_id=uuid4(),
        status="completed",
        profile="default",
        total_windows=10,
        processed_windows=10,
        total_candidates=3,
    )


@pytest.fixture
def sample_candidates(sample_run: DiscoveryRun) -> list[ClipCandidate]:
    """Create sample clip candidates."""
    return [
        ClipCandidate(
            id=uuid4(),
            run_id=sample_run.id,
            canonical_start_seconds=100.0,
            canonical_end_seconds=160.0,
            duration_seconds=60.0,
            title="High Score Candidate",
            summary="Best candidate",
            hook_type="question",
            score_v1=95.0,
            discovery_rank=1,
            is_duplicate=False,
            selected=False,
        ),
        ClipCandidate(
            id=uuid4(),
            run_id=sample_run.id,
            canonical_start_seconds=200.0,
            canonical_end_seconds=260.0,
            duration_seconds=60.0,
            title="Medium Score Candidate",
            summary="Second best",
            hook_type="story",
            score_v1=85.0,
            discovery_rank=2,
            is_duplicate=False,
            selected=True,
            selection_rank=1,
        ),
        ClipCandidate(
            id=uuid4(),
            run_id=sample_run.id,
            canonical_start_seconds=300.0,
            canonical_end_seconds=360.0,
            duration_seconds=60.0,
            title="Duplicate Candidate",
            summary="Duplicate",
            hook_type="statement",
            score_v1=80.0,
            discovery_rank=3,
            is_duplicate=True,
            selected=False,
        ),
    ]


class TestCandidateShortlistServiceInit:
    """Tests for service initialization."""

    def test_init_with_default_limit(self, mock_session: AsyncMock) -> None:
        """Test initialization with default limit."""
        service = CandidateShortlistService(mock_session)
        assert service.session is mock_session
        assert service.default_limit == 50

    def test_init_with_custom_limit(self, mock_session: AsyncMock) -> None:
        """Test initialization with custom limit."""
        service = CandidateShortlistService(mock_session, default_limit=100)
        assert service.default_limit == 100


class TestGetShortlist:
    """Tests for get_shortlist."""

    @pytest.mark.asyncio
    async def test_returns_shortlist(
        self,
        mock_session: AsyncMock,
        sample_run: DiscoveryRun,
        sample_candidates: list[ClipCandidate],
    ) -> None:
        """Test getting shortlist."""
        # Mock run query
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = sample_run

        # Mock candidates query (non-duplicates)
        non_dup_candidates = [c for c in sample_candidates if not c.is_duplicate]
        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = non_dup_candidates

        # Mock total count
        count_result = MagicMock()
        count_result.scalar.return_value = len(sample_candidates)

        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return run_result
            elif call_count == 2:
                return candidates_result
            elif call_count == 3:
                # Analysis count query
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result
            elif call_count == 4:
                # Plan count query
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result
            else:
                return count_result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateShortlistService(mock_session)
        result = await service.get_shortlist(sample_run.id)

        assert result["run_id"] == str(sample_run.id)
        assert result["workflow_id"] == str(sample_run.workflow_id)
        assert result["returned_count"] == 2  # Excludes duplicate
        assert len(result["candidates"]) == 2

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_run(self, mock_session: AsyncMock) -> None:
        """Test that nonexistent run raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = CandidateShortlistService(mock_session)

        with pytest.raises(RunNotFoundError):
            await service.get_shortlist(uuid4())

    @pytest.mark.asyncio
    async def test_rejects_non_terminal_run(
        self,
        mock_session: AsyncMock,
        sample_run: DiscoveryRun,
    ) -> None:
        """Test that non-terminal run raises error."""
        sample_run.status = "running"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_run
        mock_session.execute.return_value = mock_result

        service = CandidateShortlistService(mock_session)

        with pytest.raises(RunNotTerminalError):
            await service.get_shortlist(sample_run.id)

    @pytest.mark.asyncio
    async def test_respects_limit(
        self,
        mock_session: AsyncMock,
        sample_run: DiscoveryRun,
        sample_candidates: list[ClipCandidate],
    ) -> None:
        """Test that limit is respected."""
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = sample_run

        limited_candidates = [sample_candidates[0]]
        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = limited_candidates

        count_result = MagicMock()
        count_result.scalar.return_value = len(sample_candidates)

        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return run_result
            elif call_count == 2:
                return candidates_result
            elif call_count == 3:
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result
            elif call_count == 4:
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result
            else:
                return count_result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateShortlistService(mock_session)
        result = await service.get_shortlist(sample_run.id, limit=1)

        assert result["returned_count"] == 1

    @pytest.mark.asyncio
    async def test_includes_duplicates_when_requested(
        self,
        mock_session: AsyncMock,
        sample_run: DiscoveryRun,
        sample_candidates: list[ClipCandidate],
    ) -> None:
        """Test that duplicates are included when requested."""
        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = sample_run

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = sample_candidates

        count_result = MagicMock()
        count_result.scalar.return_value = len(sample_candidates)

        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return run_result
            elif call_count == 2:
                return candidates_result
            elif call_count == 3:
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result
            elif call_count == 4:
                result = MagicMock()
                result.__iter__ = MagicMock(return_value=iter([]))
                return result
            else:
                return count_result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateShortlistService(mock_session)
        result = await service.get_shortlist(sample_run.id, include_duplicates=True)

        assert result["returned_count"] == 3

    @pytest.mark.asyncio
    async def test_includes_analysis_and_plan_metadata(
        self,
        mock_session: AsyncMock,
        sample_run: DiscoveryRun,
        sample_candidates: list[ClipCandidate],
    ) -> None:
        """Test that has_analysis and has_plan are populated."""
        non_dup = [c for c in sample_candidates if not c.is_duplicate]
        first_candidate = non_dup[0]

        run_result = MagicMock()
        run_result.scalar_one_or_none.return_value = sample_run

        candidates_result = MagicMock()
        candidates_result.scalars.return_value.all.return_value = non_dup

        # Mock analysis count - first candidate has analysis
        analysis_row = MagicMock()
        analysis_row.candidate_id = first_candidate.id
        analysis_row.count = 1
        analysis_result = MagicMock()
        analysis_result.__iter__ = MagicMock(return_value=iter([analysis_row]))

        # Mock plan count - no plans
        plan_result = MagicMock()
        plan_result.__iter__ = MagicMock(return_value=iter([]))

        count_result = MagicMock()
        count_result.scalar.return_value = len(sample_candidates)

        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return run_result
            elif call_count == 2:
                return candidates_result
            elif call_count == 3:
                return analysis_result
            elif call_count == 4:
                return plan_result
            else:
                return count_result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateShortlistService(mock_session)
        result = await service.get_shortlist(sample_run.id)

        # First candidate has analysis
        first_item = result["candidates"][0]
        assert first_item["has_analysis"] is True
        assert first_item["has_plan"] is False


class TestGetSelectedCandidates:
    """Tests for get_selected_candidates."""

    @pytest.mark.asyncio
    async def test_returns_selected(
        self,
        mock_session: AsyncMock,
        sample_candidates: list[ClipCandidate],
    ) -> None:
        """Test getting selected candidates."""
        selected = [c for c in sample_candidates if c.selected]
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = selected
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        service = CandidateShortlistService(mock_session)
        result = await service.get_selected_candidates(uuid4())

        assert len(result) == 1
        assert result[0]["selection_rank"] == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_none_selected(
        self,
        mock_session: AsyncMock,
    ) -> None:
        """Test returning empty list when no candidates selected."""
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute.return_value = mock_result

        service = CandidateShortlistService(mock_session)
        result = await service.get_selected_candidates(uuid4())

        assert result == []
