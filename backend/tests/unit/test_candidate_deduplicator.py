"""Unit tests for CandidateDeduplicator."""

from uuid import uuid4

import pytest

from app.services.candidate_deduplicator import (
    DEFAULT_IOU_THRESHOLD,
    CandidateDeduplicator,
    CandidateForDedup,
    deduplicate_candidates,
)


def make_candidate(start: float, end: float, score: float = 50.0) -> CandidateForDedup:
    """Create a test candidate."""
    return CandidateForDedup(
        id=uuid4(),
        start_seconds=start,
        end_seconds=end,
        score=score,
    )


class TestCandidateDeduplicator:
    """Tests for CandidateDeduplicator."""

    def test_init_default_threshold(self) -> None:
        """Test default IoU threshold."""
        deduplicator = CandidateDeduplicator()
        assert deduplicator.iou_threshold == DEFAULT_IOU_THRESHOLD

    def test_init_custom_threshold(self) -> None:
        """Test custom IoU threshold."""
        deduplicator = CandidateDeduplicator(iou_threshold=0.7)
        assert deduplicator.iou_threshold == 0.7

    def test_init_invalid_threshold_low(self) -> None:
        """Test that threshold below 0 raises error."""
        with pytest.raises(ValueError):
            CandidateDeduplicator(iou_threshold=-0.1)

    def test_init_invalid_threshold_high(self) -> None:
        """Test that threshold above 1 raises error."""
        with pytest.raises(ValueError):
            CandidateDeduplicator(iou_threshold=1.1)

    def test_deduplicate_empty_list(self) -> None:
        """Test deduplication of empty list."""
        deduplicator = CandidateDeduplicator()
        results = deduplicator.deduplicate([])
        assert results == []

    def test_deduplicate_single_candidate(self) -> None:
        """Test deduplication of single candidate."""
        deduplicator = CandidateDeduplicator()
        candidate = make_candidate(0.0, 60.0)
        results = deduplicator.deduplicate([candidate])

        assert len(results) == 1
        assert results[0].is_duplicate is False
        assert results[0].duplicate_of_id is None

    def test_deduplicate_no_overlap(self) -> None:
        """Test candidates with no overlap are not duplicates."""
        deduplicator = CandidateDeduplicator()
        candidates = [
            make_candidate(0.0, 60.0, score=80.0),
            make_candidate(120.0, 180.0, score=70.0),
        ]
        results = deduplicator.deduplicate(candidates)

        assert len(results) == 2
        assert all(not r.is_duplicate for r in results)

    def test_deduplicate_full_overlap(self) -> None:
        """Test candidates with full overlap are duplicates."""
        deduplicator = CandidateDeduplicator()
        candidates = [
            make_candidate(0.0, 60.0, score=80.0),
            make_candidate(0.0, 60.0, score=70.0),  # Same times, lower score
        ]
        results = deduplicator.deduplicate(candidates)

        # Lower scored one should be duplicate
        duplicates = [r for r in results if r.is_duplicate]
        assert len(duplicates) == 1
        assert duplicates[0].iou_with_original == 1.0

    def test_deduplicate_partial_overlap(self) -> None:
        """Test candidates with partial overlap."""
        deduplicator = CandidateDeduplicator(iou_threshold=0.3)
        candidates = [
            make_candidate(0.0, 60.0, score=80.0),
            make_candidate(30.0, 90.0, score=70.0),  # 30s overlap
        ]
        results = deduplicator.deduplicate(candidates)

        # With threshold 0.3, should be marked as duplicate
        # IoU = 30 / (60 + 60 - 30) = 30/90 = 0.33
        duplicates = [r for r in results if r.is_duplicate]
        assert len(duplicates) == 1

    def test_deduplicate_keeps_higher_score(self) -> None:
        """Test that higher scored candidate is kept."""
        deduplicator = CandidateDeduplicator()
        candidates = [
            make_candidate(0.0, 60.0, score=70.0),
            make_candidate(0.0, 60.0, score=80.0),  # Same times, higher score
        ]
        results = deduplicator.deduplicate(candidates)

        # Lower scored one (70) should be duplicate
        for r in results:
            if r.is_duplicate:
                # Find the original candidate
                orig = next(c for c in candidates if c.id == r.duplicate_of_id)
                assert orig.score == 80.0

    def test_deduplicate_multiple_overlapping(self) -> None:
        """Test deduplication of multiple overlapping candidates."""
        deduplicator = CandidateDeduplicator(iou_threshold=0.5)
        candidates = [
            make_candidate(0.0, 60.0, score=90.0),
            make_candidate(10.0, 70.0, score=80.0),
            make_candidate(20.0, 80.0, score=70.0),
            make_candidate(200.0, 260.0, score=60.0),  # Non-overlapping
        ]
        results = deduplicator.deduplicate(candidates)

        non_duplicates = [r for r in results if not r.is_duplicate]
        # At least the highest scoring and the non-overlapping one
        assert len(non_duplicates) >= 2


class TestCalculateIou:
    """Tests for IoU calculation."""

    def test_no_overlap(self) -> None:
        """Test IoU for non-overlapping candidates."""
        deduplicator = CandidateDeduplicator()
        c1 = make_candidate(0.0, 60.0)
        c2 = make_candidate(120.0, 180.0)

        iou = deduplicator._calculate_iou(c1, c2)
        assert iou == 0.0

    def test_full_overlap(self) -> None:
        """Test IoU for fully overlapping candidates."""
        deduplicator = CandidateDeduplicator()
        c1 = make_candidate(0.0, 60.0)
        c2 = make_candidate(0.0, 60.0)

        iou = deduplicator._calculate_iou(c1, c2)
        assert iou == 1.0

    def test_partial_overlap(self) -> None:
        """Test IoU for partial overlap."""
        deduplicator = CandidateDeduplicator()
        c1 = make_candidate(0.0, 60.0)  # 60s duration
        c2 = make_candidate(30.0, 90.0)  # 60s duration, 30s overlap

        iou = deduplicator._calculate_iou(c1, c2)
        # IoU = 30 / (60 + 60 - 30) = 30/90 = 0.333...
        assert abs(iou - 0.333) < 0.01

    def test_one_contains_other(self) -> None:
        """Test IoU when one candidate contains the other."""
        deduplicator = CandidateDeduplicator()
        c1 = make_candidate(0.0, 100.0)  # 100s duration
        c2 = make_candidate(20.0, 60.0)  # 40s duration, fully contained

        iou = deduplicator._calculate_iou(c1, c2)
        # IoU = 40 / (100 + 40 - 40) = 40/100 = 0.4
        assert abs(iou - 0.4) < 0.01


class TestFindOverlappingCandidates:
    """Tests for finding overlapping candidates."""

    def test_find_overlapping(self) -> None:
        """Test finding overlapping candidates."""
        deduplicator = CandidateDeduplicator()
        target = make_candidate(0.0, 60.0)
        candidates = [
            make_candidate(30.0, 90.0),  # Overlaps 30s
            make_candidate(120.0, 180.0),  # No overlap
            make_candidate(50.0, 100.0),  # Overlaps 10s
        ]

        overlapping = deduplicator.find_overlapping_candidates(
            target, candidates, min_overlap_seconds=5.0
        )

        assert len(overlapping) == 2

    def test_find_overlapping_with_min_threshold(self) -> None:
        """Test finding overlapping candidates with minimum threshold."""
        deduplicator = CandidateDeduplicator()
        target = make_candidate(0.0, 60.0)
        candidates = [
            make_candidate(50.0, 90.0),  # Overlaps 10s
            make_candidate(55.0, 100.0),  # Overlaps 5s
        ]

        overlapping = deduplicator.find_overlapping_candidates(
            target, candidates, min_overlap_seconds=10.0
        )

        assert len(overlapping) == 1


class TestConvenienceFunction:
    """Tests for convenience function."""

    def test_deduplicate_candidates_function(self) -> None:
        """Test the convenience function."""
        candidates = [
            make_candidate(0.0, 60.0, score=80.0),
            make_candidate(0.0, 60.0, score=70.0),
        ]
        results = deduplicate_candidates(candidates)

        assert len(results) == 2
        duplicates = [r for r in results if r.is_duplicate]
        assert len(duplicates) == 1
