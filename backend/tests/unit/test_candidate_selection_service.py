"""Unit tests for CandidateSelectionService."""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ClipCandidate, DiscoveryRun
from app.services.candidate_selection_service import (
    CandidateNotFoundError,
    CandidateSelectionService,
    DuplicateSelectionError,
    RunNotTerminalError,
    SelectionError,
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
        selected=False,
        selection_rank=None,
    )


class TestCandidateSelectionServiceInit:
    """Tests for service initialization."""

    def test_init(self, mock_session: AsyncMock) -> None:
        """Test service initialization."""
        service = CandidateSelectionService(mock_session)
        assert service.session is mock_session
        assert "completed" in service.TERMINAL_STATES
        assert "completed_with_errors" in service.TERMINAL_STATES
        # NOTE: "failed" is intentionally excluded - fully failed runs have no valid candidates
        assert "failed" not in service.TERMINAL_STATES
        assert "running" not in service.TERMINAL_STATES


class TestSelectCandidate:
    """Tests for select_candidate."""

    @pytest.mark.asyncio
    async def test_selects_candidate(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
        sample_run: DiscoveryRun,
    ) -> None:
        """Test successful candidate selection."""
        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # First call: get candidate
                result.scalar_one_or_none.return_value = sample_candidate
            else:
                # Second call: get run
                result.scalar_one_or_none.return_value = sample_run
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateSelectionService(mock_session)
        result = await service.select_candidate(sample_candidate.id, selection_rank=1)

        assert result.selected is True
        assert result.selection_rank == 1
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_candidate(self, mock_session: AsyncMock) -> None:
        """Test that nonexistent candidate raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)

        with pytest.raises(CandidateNotFoundError):
            await service.select_candidate(uuid4())

    @pytest.mark.asyncio
    async def test_rejects_duplicate_candidate(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
    ) -> None:
        """Test that duplicate candidates raise error."""
        sample_candidate.is_duplicate = True

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_candidate
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)

        with pytest.raises(DuplicateSelectionError):
            await service.select_candidate(sample_candidate.id)

    @pytest.mark.asyncio
    async def test_rejects_non_terminal_run(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
        sample_run: DiscoveryRun,
    ) -> None:
        """Test that non-terminal run raises error."""
        sample_run.status = "running"

        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = sample_candidate
            else:
                result.scalar_one_or_none.return_value = sample_run
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateSelectionService(mock_session)

        with pytest.raises(RunNotTerminalError):
            await service.select_candidate(sample_candidate.id)

    @pytest.mark.asyncio
    async def test_rejects_invalid_rank(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
        sample_run: DiscoveryRun,
    ) -> None:
        """Test that rank < 1 raises error."""
        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = sample_candidate
            else:
                result.scalar_one_or_none.return_value = sample_run
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateSelectionService(mock_session)

        with pytest.raises(SelectionError) as exc_info:
            await service.select_candidate(sample_candidate.id, selection_rank=0)

        assert "must be >= 1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_select_without_rank(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
        sample_run: DiscoveryRun,
    ) -> None:
        """Test selecting without rank doesn't set rank."""
        call_count = 0

        def execute_side_effect(query):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = sample_candidate
            else:
                result.scalar_one_or_none.return_value = sample_run
            return result

        mock_session.execute.side_effect = execute_side_effect

        service = CandidateSelectionService(mock_session)
        result = await service.select_candidate(sample_candidate.id, selection_rank=None)

        assert result.selected is True
        assert result.selection_rank is None


class TestUnselectCandidate:
    """Tests for unselect_candidate."""

    @pytest.mark.asyncio
    async def test_unselects_candidate(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
    ) -> None:
        """Test successful candidate unselection."""
        sample_candidate.selected = True
        sample_candidate.selection_rank = 3

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_candidate
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)
        result = await service.unselect_candidate(sample_candidate.id)

        assert result.selected is False
        assert result.selection_rank is None
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_candidate(self, mock_session: AsyncMock) -> None:
        """Test that nonexistent candidate raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)

        with pytest.raises(CandidateNotFoundError):
            await service.unselect_candidate(uuid4())


class TestSetSelectionRank:
    """Tests for set_selection_rank."""

    @pytest.mark.asyncio
    async def test_sets_rank(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
    ) -> None:
        """Test setting selection rank."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_candidate
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)
        result = await service.set_selection_rank(sample_candidate.id, 5)

        assert result.selection_rank == 5
        mock_session.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_rank(self, mock_session: AsyncMock) -> None:
        """Test that rank < 1 raises error."""
        service = CandidateSelectionService(mock_session)

        with pytest.raises(SelectionError) as exc_info:
            await service.set_selection_rank(uuid4(), 0)

        assert "must be >= 1" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_candidate(self, mock_session: AsyncMock) -> None:
        """Test that nonexistent candidate raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)

        with pytest.raises(CandidateNotFoundError):
            await service.set_selection_rank(uuid4(), 5)


class TestGetSelectionState:
    """Tests for get_selection_state."""

    @pytest.mark.asyncio
    async def test_returns_state(
        self,
        mock_session: AsyncMock,
        sample_candidate: ClipCandidate,
    ) -> None:
        """Test getting selection state."""
        sample_candidate.selected = True
        sample_candidate.selection_rank = 2

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_candidate
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)
        result = await service.get_selection_state(sample_candidate.id)

        assert result["candidate_id"] == str(sample_candidate.id)
        assert result["selected"] is True
        assert result["selection_rank"] == 2
        assert result["is_duplicate"] is False

    @pytest.mark.asyncio
    async def test_rejects_nonexistent_candidate(self, mock_session: AsyncMock) -> None:
        """Test that nonexistent candidate raises error."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_result

        service = CandidateSelectionService(mock_session)

        with pytest.raises(CandidateNotFoundError):
            await service.get_selection_state(uuid4())


class TestBulkSelection:
    """Tests for bulk_selection."""

    @pytest.mark.asyncio
    async def test_bulk_select_success(self, mock_session: AsyncMock) -> None:
        """Test bulk selection with mocked service."""
        service = CandidateSelectionService(mock_session)

        # Mock select_candidate to succeed
        service.select_candidate = AsyncMock(return_value=MagicMock(selected=True, selection_rank=1))

        candidate_id = uuid4()
        results = await service.bulk_selection([candidate_id], selected=True)

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["candidate_id"] == str(candidate_id)

    @pytest.mark.asyncio
    async def test_bulk_select_partial_failure(self, mock_session: AsyncMock) -> None:
        """Test bulk selection with partial failure."""
        service = CandidateSelectionService(mock_session)

        # Mock select_candidate to raise for first call, succeed for second
        service.select_candidate = AsyncMock(
            side_effect=[
                DuplicateSelectionError("duplicate"),
                MagicMock(selected=True, selection_rank=1),
            ]
        )

        ids = [uuid4(), uuid4()]
        results = await service.bulk_selection(ids, selected=True)

        assert len(results) == 2
        assert results[0]["success"] is False
        assert results[1]["success"] is True

    @pytest.mark.asyncio
    async def test_bulk_unselect(self, mock_session: AsyncMock) -> None:
        """Test bulk unselection."""
        service = CandidateSelectionService(mock_session)

        service.unselect_candidate = AsyncMock(return_value=MagicMock(selected=False, selection_rank=None))

        candidate_id = uuid4()
        results = await service.bulk_selection([candidate_id], selected=False)

        assert len(results) == 1
        assert results[0]["success"] is True
        assert results[0]["selected"] is False
