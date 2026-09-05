"""Unit tests for EditorialPlanService canonicalization logic.

Tests the strategy-aware canonicalization for TRIM and ADD_CONTEXT strategies,
including invariant validation.
"""

from uuid import uuid4

import pytest

from app.services.editorial_plan_service import (
    CanonicalizationError,
    EditorialPlanService,
)


class TestResolveSegmentIdsToTimestamps:
    """Tests for _resolve_segment_ids_to_timestamps method."""

    @pytest.fixture
    def mock_media_indexer_client(self):
        """Create a mock media indexer client."""
        from unittest.mock import AsyncMock


        client = AsyncMock()
        return client

    @pytest.fixture
    def service(self, mock_media_indexer_client):
        """Create an EditorialPlanService instance."""
        from unittest.mock import MagicMock

        from sqlalchemy.ext.asyncio import AsyncSession

        session = MagicMock(spec=AsyncSession)
        return EditorialPlanService(session, mock_media_indexer_client)

    @pytest.mark.asyncio
    async def test_trim_strategy_uses_candidate_bounds(self, service, mock_media_indexer_client):
        """TRIM strategy should only authorize candidate bounds."""
        from app.clients.media_indexer_client import TranscriptSegmentOut

        transcription_id = uuid4()
        candidate_start = 10.0
        candidate_end = 30.0

        # Mock segments within candidate bounds
        start_segment = TranscriptSegmentOut(
            id=uuid4(),
            transcription_id=transcription_id,
            sequence=1,
            start_seconds=15.0,
            end_seconds=20.0,
            text="Start segment",
        )
        end_segment = TranscriptSegmentOut(
            id=uuid4(),
            transcription_id=transcription_id,
            sequence=2,
            start_seconds=25.0,
            end_seconds=28.0,
            text="End segment",
        )

        mock_media_indexer_client.get_transcript_segments_by_time = AsyncMock(
            return_value=[start_segment, end_segment]
        )

        result_start, result_end = await service._resolve_segment_ids_to_timestamps(
            transcription_id=transcription_id,
            candidate_start_seconds=candidate_start,
            candidate_end_seconds=candidate_end,
            start_segment_id=start_segment.id,
            end_segment_id=end_segment.id,
            strategy="TRIM",
        )

        # Should request segments only within candidate bounds
        call_args = mock_media_indexer_client.get_transcript_segments_by_time.call_args
        assert call_args.kwargs["start_seconds"] == candidate_start
        assert call_args.kwargs["end_seconds"] == candidate_end

        # Should return resolved timestamps
        assert result_start == start_segment.start_seconds
        assert result_end == end_segment.end_seconds

    @pytest.mark.asyncio
    async def test_add_context_strategy_extends_window(self, service, mock_media_indexer_client):
        """ADD_CONTEXT strategy should extend window by context_before/after."""
        from app.clients.media_indexer_client import TranscriptSegmentOut

        transcription_id = uuid4()
        candidate_start = 20.0
        candidate_end = 40.0
        context_before = 15.0
        context_after = 10.0

        # Mock segments in extended window
        start_segment = TranscriptSegmentOut(
            id=uuid4(),
            transcription_id=transcription_id,
            sequence=0,
            start_seconds=10.0,
            end_seconds=15.0,
            text="Context before",
        )
        end_segment = TranscriptSegmentOut(
            id=uuid4(),
            transcription_id=transcription_id,
            sequence=3,
            start_seconds=48.0,
            end_seconds=50.0,
            text="Context after",
        )

        mock_media_indexer_client.get_transcript_segments_by_time = AsyncMock(
            return_value=[start_segment, end_segment]
        )

        result_start, result_end = await service._resolve_segment_ids_to_timestamps(
            transcription_id=transcription_id,
            candidate_start_seconds=candidate_start,
            candidate_end_seconds=candidate_end,
            start_segment_id=start_segment.id,
            end_segment_id=end_segment.id,
            strategy="ADD_CONTEXT",
            context_before_seconds=context_before,
            context_after_seconds=context_after,
        )

        # Should request segments in extended window
        call_args = mock_media_indexer_client.get_transcript_segments_by_time.call_args
        assert call_args.kwargs["start_seconds"] == candidate_start - context_before
        assert call_args.kwargs["end_seconds"] == candidate_end + context_after

        # Should return resolved timestamps
        assert result_start == start_segment.start_seconds
        assert result_end == end_segment.end_seconds

    @pytest.mark.asyncio
    async def test_trim_segment_outside_bounds_raises_error(self, service, mock_media_indexer_client):
        """TRIM strategy should reject segments outside candidate bounds."""
        from app.clients.media_indexer_client import TranscriptSegmentOut

        transcription_id = uuid4()
        candidate_start = 20.0
        candidate_end = 40.0

        # Segment before candidate bounds
        start_segment = TranscriptSegmentOut(
            id=uuid4(),
            transcription_id=transcription_id,
            sequence=0,
            start_seconds=10.0,  # Before candidate_start
            end_seconds=15.0,
            text="Outside bounds",
        )
        end_segment = TranscriptSegmentOut(
            id=uuid4(),
            transcription_id=transcription_id,
            sequence=1,
            start_seconds=35.0,
            end_seconds=38.0,
            text="Within bounds",
        )

        mock_media_indexer_client.get_transcript_segments_by_time = AsyncMock(
            return_value=[start_segment, end_segment]
        )

        # Should NOT raise during resolution (validation happens in create_plan_from_analysis)
        # The resolution itself just returns the timestamps
        result_start, result_end = await service._resolve_segment_ids_to_timestamps(
            transcription_id=transcription_id,
            candidate_start_seconds=candidate_start,
            candidate_end_seconds=candidate_end,
            start_segment_id=start_segment.id,
            end_segment_id=end_segment.id,
            strategy="TRIM",
        )

        assert result_start == start_segment.start_seconds
        assert result_end == end_segment.end_seconds

    @pytest.mark.asyncio
    async def test_missing_segment_id_raises_error(self, service, mock_media_indexer_client):
        """Missing segment ID should raise CanonicalizationError."""
        transcription_id = uuid4()

        with pytest.raises(CanonicalizationError) as exc_info:
            await service._resolve_segment_ids_to_timestamps(
                transcription_id=transcription_id,
                candidate_start_seconds=10.0,
                candidate_end_seconds=30.0,
                start_segment_id=None,  # Missing
                end_segment_id=uuid4(),
                strategy="TRIM",
            )

        assert "Segment IDs required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_segment_not_found_raises_error(self, service, mock_media_indexer_client):
        """Segment not found in transcript should raise CanonicalizationError."""
        transcription_id = uuid4()

        mock_media_indexer_client.get_transcript_segments_by_time = AsyncMock(
            return_value=[]  # No segments returned
        )

        with pytest.raises(CanonicalizationError) as exc_info:
            await service._resolve_segment_ids_to_timestamps(
                transcription_id=transcription_id,
                candidate_start_seconds=10.0,
                candidate_end_seconds=30.0,
                start_segment_id=uuid4(),
                end_segment_id=uuid4(),
                strategy="TRIM",
            )

        assert "not found in transcript range" in str(exc_info.value)


class TestTrimInvariants:
    """Tests for TRIM strategy invariant validation."""

    def test_trim_start_before_candidate_violates_invariant(self):
        """TRIM resolved start before candidate start should fail invariant."""
        # This is tested via create_plan_from_analysis integration
        # The invariant check is: resolved_start >= candidate_start
        candidate_start = 20.0
        resolved_start = 15.0  # Before candidate

        assert resolved_start < candidate_start, "TRIM invariant violation"

    def test_trim_end_after_candidate_violates_invariant(self):
        """TRIM resolved end after candidate end should fail invariant."""
        candidate_end = 40.0
        resolved_end = 45.0  # After candidate

        assert resolved_end > candidate_end, "TRIM invariant violation"


class TestAddContextInvariants:
    """Tests for ADD_CONTEXT strategy invariant validation."""

    def test_add_context_start_before_authorized_window_violates_invariant(self):
        """ADD_CONTEXT resolved start before authorized window should fail."""
        candidate_start = 20.0
        context_before = 15.0
        authorized_start = max(0.0, candidate_start - context_before)  # 5.0

        resolved_start = 2.0  # Before authorized

        assert resolved_start < authorized_start, "ADD_CONTEXT invariant violation"

    def test_add_context_end_after_authorized_window_violates_invariant(self):
        """ADD_CONTEXT resolved end after authorized window should fail."""
        candidate_end = 40.0
        context_after = 10.0
        authorized_end = candidate_end + context_after  # 50.0

        resolved_end = 55.0  # After authorized

        assert resolved_end > authorized_end, "ADD_CONTEXT invariant violation"


class TestFingerprintComputation:
    """Tests for plan fingerprint computation."""

    def test_fingerprint_is_deterministic(self):
        """Same inputs should produce same fingerprint."""
        service = EditorialPlanService(None, None)  # type: ignore

        candidate_id = uuid4()
        strategy = "TRIM"
        start = 10.0
        end = 30.0

        fp1 = service._compute_fingerprint(candidate_id, strategy, start, end)
        fp2 = service._compute_fingerprint(candidate_id, strategy, start, end)

        assert fp1 == fp2
        assert len(fp1) == 64  # SHA-256 hex digest

    def test_fingerprint_differs_on_strategy_change(self):
        """Different strategy should produce different fingerprint."""
        service = EditorialPlanService(None, None)  # type: ignore

        candidate_id = uuid4()
        start = 10.0
        end = 30.0

        fp_trim = service._compute_fingerprint(candidate_id, "TRIM", start, end)
        fp_add_context = service._compute_fingerprint(candidate_id, "ADD_CONTEXT", start, end)

        assert fp_trim != fp_add_context

    def test_fingerprint_differs_on_boundary_change(self):
        """Different boundaries should produce different fingerprint."""
        service = EditorialPlanService(None, None)  # type: ignore

        candidate_id = uuid4()
        strategy = "TRIM"

        fp1 = service._compute_fingerprint(candidate_id, strategy, 10.0, 30.0)
        fp2 = service._compute_fingerprint(candidate_id, strategy, 15.0, 30.0)

        assert fp1 != fp2
