"""CandidateCanonicalizer for resolving segment IDs to trusted timestamps.

The LLM returns segment IDs for clip boundaries. This module resolves
those IDs to trusted timestamps from the transcript, ensuring temporal
accuracy independent of LLM hallucinations.
"""

from uuid import UUID

from app.clients.media_indexer_client import TranscriptSegmentOut
from app.schemas.discovery import LLMClipSuggestion


class CanonicalizationError(Exception):
    """Raised when canonicalization fails."""

    pass


class CandidateCanonicalizer:
    """
    Resolves LLM-suggested segment IDs to trusted timestamps.

    The LLM acts as a semantic judge but is not a source of temporal truth.
    This canonicalizer ensures that clip boundaries are resolved against
    the actual transcript data from Media Indexer.

    Process:
    1. LLM returns start_segment_id and end_segment_id
    2. Canonicalizer looks up these IDs in the transcript
    3. Returns canonical_start_seconds and canonical_end_seconds

    This prevents issues where the LLM might:
    - Invent non-existent timestamps
    - Misremember segment boundaries
    - Confuse segment order
    """

    def __init__(self, segments: list[TranscriptSegmentOut]) -> None:
        """
        Initialize canonicalizer with transcript segments.

        Args:
            segments: List of transcript segments from Media Indexer
        """
        self.segments = segments
        self._segment_map = {seg.id: seg for seg in segments}

    def canonicalize(self, suggestion: LLMClipSuggestion) -> tuple[float, float, float]:
        """
        Resolve segment IDs to canonical timestamps.

        Args:
            suggestion: LLM clip suggestion with segment IDs

        Returns:
            Tuple of (start_seconds, end_seconds, duration_seconds)

        Raises:
            CanonicalizationError: If segment IDs cannot be resolved
        """
        start_segment = self._segment_map.get(suggestion.start_segment_id)
        if not start_segment:
            raise CanonicalizationError(
                f"Start segment {suggestion.start_segment_id} not found"
            )

        end_segment = self._segment_map.get(suggestion.end_segment_id)
        if not end_segment:
            raise CanonicalizationError(
                f"End segment {suggestion.end_segment_id} not found"
            )

        # Validate segment order
        if start_segment.start_seconds > end_segment.end_seconds:
            raise CanonicalizationError(
                f"Invalid segment order: start ({start_segment.start_seconds}s) "
                f"after end ({end_segment.end_seconds}s)"
            )

        # Use segment start for clip start, segment end for clip end
        canonical_start = start_segment.start_seconds
        canonical_end = end_segment.end_seconds
        duration = canonical_end - canonical_start

        # Validate duration is reasonable (15-180 seconds)
        if duration < 15:
            raise CanonicalizationError(
                f"Clip too short: {duration:.1f}s (minimum 15s)"
            )
        if duration > 180:
            raise CanonicalizationError(
                f"Clip too long: {duration:.1f}s (maximum 180s)"
            )

        return canonical_start, canonical_end, duration

    def canonicalize_batch(
        self, suggestions: list[LLMClipSuggestion]
    ) -> list[tuple[LLMClipSuggestion, tuple[float, float, float]]]:
        """
        Canonicalize multiple suggestions.

        Args:
            suggestions: List of LLM clip suggestions

        Returns:
            List of (suggestion, (start, end, duration)) tuples
            Only includes successfully canonicalized suggestions.
        """
        results = []
        for suggestion in suggestions:
            try:
                timestamps = self.canonicalize(suggestion)
                results.append((suggestion, timestamps))
            except CanonicalizationError:
                # Skip invalid suggestions
                continue
        return results

    def get_segment_by_id(self, segment_id: UUID) -> TranscriptSegmentOut | None:
        """Get a segment by its ID."""
        return self._segment_map.get(segment_id)

    def get_segments_in_range(
        self, start_seconds: float, end_seconds: float
    ) -> list[TranscriptSegmentOut]:
        """
        Get all segments that overlap with a time range.

        Args:
            start_seconds: Start of range
            end_seconds: End of range

        Returns:
            List of overlapping segments, sorted by start time
        """
        overlapping = [
            seg
            for seg in self.segments
            if seg.start_seconds < end_seconds and seg.end_seconds > start_seconds
        ]
        return sorted(overlapping, key=lambda s: s.start_seconds)
