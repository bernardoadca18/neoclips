"""CandidateDeduplicator using temporal IoU.

Deduplicates clip candidates based on temporal overlap.
Uses Intersection over Union (IoU) to measure overlap similarity.
Candidates with IoU >= threshold are marked as duplicates.
"""

from dataclasses import dataclass
from uuid import UUID


@dataclass
class CandidateForDedup:
    """Minimal candidate data for deduplication."""

    id: UUID
    start_seconds: float
    end_seconds: float
    score: float


@dataclass
class DeduplicationResult:
    """Result of deduplication for a single candidate."""

    candidate_id: UUID
    is_duplicate: bool
    duplicate_of_id: UUID | None
    iou_with_original: float | None


# Default IoU threshold for duplicate detection
# Higher = more overlap required to be considered duplicate
DEFAULT_IOU_THRESHOLD = 0.5


class CandidateDeduplicator:
    """
    Deduplicates clip candidates using temporal IoU.

    Algorithm:
    1. Sort candidates by score (descending)
    2. For each candidate, check against all non-duplicate candidates
    3. If IoU >= threshold, mark as duplicate of the higher-scored candidate

    This ensures we keep the best candidate from each overlapping group.
    """

    def __init__(self, iou_threshold: float = DEFAULT_IOU_THRESHOLD) -> None:
        """
        Initialize deduplicator.

        Args:
            iou_threshold: Minimum IoU to consider as duplicate (0.0-1.0)
        """
        if not 0.0 <= iou_threshold <= 1.0:
            raise ValueError("iou_threshold must be between 0 and 1")
        self.iou_threshold = iou_threshold

    def deduplicate(
        self, candidates: list[CandidateForDedup]
    ) -> list[DeduplicationResult]:
        """
        Deduplicate candidates based on temporal overlap.

        Args:
            candidates: List of candidates to deduplicate

        Returns:
            List of DeduplicationResult for each candidate
        """
        if not candidates:
            return []

        # Sort by score descending
        sorted_candidates = sorted(candidates, key=lambda c: c.score, reverse=True)

        # Track non-duplicate candidates
        non_duplicates: list[CandidateForDedup] = []
        results: list[DeduplicationResult] = []

        for candidate in sorted_candidates:
            # Check against all non-duplicate candidates
            best_match: CandidateForDedup | None = None
            best_iou = 0.0

            for non_dup in non_duplicates:
                iou = self._calculate_iou(candidate, non_dup)
                if iou >= self.iou_threshold and iou > best_iou:
                    best_match = non_dup
                    best_iou = iou

            if best_match is not None:
                # Mark as duplicate
                results.append(
                    DeduplicationResult(
                        candidate_id=candidate.id,
                        is_duplicate=True,
                        duplicate_of_id=best_match.id,
                        iou_with_original=best_iou,
                    )
                )
            else:
                # Not a duplicate, add to non-duplicates
                non_duplicates.append(candidate)
                results.append(
                    DeduplicationResult(
                        candidate_id=candidate.id,
                        is_duplicate=False,
                        duplicate_of_id=None,
                        iou_with_original=None,
                    )
                )

        return results

    def _calculate_iou(
        self, cand1: CandidateForDedup, cand2: CandidateForDedup
    ) -> float:
        """
        Calculate Intersection over Union for two candidates.

        IoU = intersection / union

        Returns 0.0 if candidates don't overlap.
        """
        # Calculate intersection
        intersection_start = max(cand1.start_seconds, cand2.start_seconds)
        intersection_end = min(cand1.end_seconds, cand2.end_seconds)

        if intersection_start >= intersection_end:
            return 0.0  # No overlap

        intersection = intersection_end - intersection_start

        # Calculate union
        duration1 = cand1.end_seconds - cand1.start_seconds
        duration2 = cand2.end_seconds - cand2.start_seconds
        union = duration1 + duration2 - intersection

        if union <= 0:
            return 0.0

        return intersection / union

    def find_overlapping_candidates(
        self,
        target: CandidateForDedup,
        candidates: list[CandidateForDedup],
        min_overlap_seconds: float = 5.0,
    ) -> list[tuple[CandidateForDedup, float]]:
        """
        Find candidates that overlap with a target candidate.

        Args:
            target: The candidate to check against
            candidates: List of candidates to check
            min_overlap_seconds: Minimum overlap to include

        Returns:
            List of (candidate, overlap_seconds) tuples
        """
        overlapping = []

        for candidate in candidates:
            if candidate.id == target.id:
                continue

            # Calculate overlap
            intersection_start = max(target.start_seconds, candidate.start_seconds)
            intersection_end = min(target.end_seconds, candidate.end_seconds)

            if intersection_start < intersection_end:
                overlap = intersection_end - intersection_start
                if overlap >= min_overlap_seconds:
                    overlapping.append((candidate, overlap))

        return overlapping


def deduplicate_candidates(
    candidates: list[CandidateForDedup],
    iou_threshold: float = DEFAULT_IOU_THRESHOLD,
) -> list[DeduplicationResult]:
    """
    Convenience function to deduplicate candidates.

    Args:
        candidates: List of candidates to deduplicate
        iou_threshold: Minimum IoU to consider as duplicate

    Returns:
        List of DeduplicationResult for each candidate
    """
    deduplicator = CandidateDeduplicator(iou_threshold)
    return deduplicator.deduplicate(candidates)
