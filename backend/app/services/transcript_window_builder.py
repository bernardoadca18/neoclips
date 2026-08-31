"""TranscriptWindowBuilder for bounded transcript processing.

Creates overlapping windows from transcript segments for LLM processing.
Windows have configurable duration and overlap to ensure clip candidates
spanning window boundaries are captured.
"""

from dataclasses import dataclass

from app.clients.media_indexer_client import TranscriptSegmentOut


@dataclass
class WindowConfig:
    """Configuration for window building."""

    window_duration_seconds: float = 300.0  # 5 minutes default
    overlap_seconds: float = 60.0  # 1 minute overlap
    min_segment_count: int = 3  # Minimum segments per window


@dataclass
class TranscriptWindow:
    """A bounded window of transcript segments."""

    window_index: int
    start_seconds: float
    end_seconds: float
    segments: list[TranscriptSegmentOut]

    @property
    def segment_count(self) -> int:
        """Return the number of segments in this window."""
        return len(self.segments)


class TranscriptWindowBuilder:
    """
    Builds overlapping windows from transcript segments.

    The overlap ensures that clip candidates spanning window boundaries
    are still captured. Each window contains complete segments.

    Example:
        config = WindowConfig(window_duration_seconds=300, overlap_seconds=60)
        builder = TranscriptWindowBuilder(config)
        windows = builder.build(segments)
    """

    def __init__(self, config: WindowConfig | None = None) -> None:
        self.config = config or WindowConfig()

    def build(self, segments: list[TranscriptSegmentOut]) -> list[TranscriptWindow]:
        """
        Build windows from transcript segments.

        Segments are assigned to windows based on their start time.
        Overlap ensures coverage of cross-boundary clips.

        Args:
            segments: List of transcript segments from Media Indexer

        Returns:
            List of TranscriptWindow objects
        """
        if not segments:
            return []

        # Sort segments by start time
        sorted_segments = sorted(segments, key=lambda s: s.start_seconds)

        total_duration = sorted_segments[-1].end_seconds
        window_duration = self.config.window_duration_seconds
        overlap = self.config.overlap_seconds

        # Calculate window boundaries
        # Step is (window_duration - overlap) to achieve desired overlap
        step = window_duration - overlap
        if step <= 0:
            raise ValueError("Overlap must be less than window duration")

        windows: list[TranscriptWindow] = []
        window_index = 0
        current_start = 0.0

        while current_start < total_duration:
            window_end = min(current_start + window_duration, total_duration)

            # Collect segments that overlap with this window
            window_segments = [
                seg
                for seg in sorted_segments
                if seg.start_seconds < window_end and seg.end_seconds > current_start
            ]

            # Only create window if it has enough segments
            if len(window_segments) >= self.config.min_segment_count:
                windows.append(
                    TranscriptWindow(
                        window_index=window_index,
                        start_seconds=current_start,
                        end_seconds=window_end,
                        segments=window_segments,
                    )
                )
                window_index += 1

            # Move to next window position
            current_start += step

            # Stop if we've covered the entire transcript
            if current_start >= total_duration:
                break

        return windows

    def build_for_time_range(
        self,
        segments: list[TranscriptSegmentOut],
        start_seconds: float,
        end_seconds: float,
    ) -> TranscriptWindow:
        """
        Build a single window for a specific time range.

        Useful for reprocessing specific sections or targeted discovery.

        Args:
            segments: List of transcript segments
            start_seconds: Start of the time range
            end_seconds: End of the time range

        Returns:
            A TranscriptWindow for the specified range
        """
        # Filter segments that overlap with the time range
        window_segments = [
            seg
            for seg in segments
            if seg.start_seconds < end_seconds and seg.end_seconds > start_seconds
        ]

        # Sort by start time
        window_segments.sort(key=lambda s: s.start_seconds)

        return TranscriptWindow(
            window_index=0,
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            segments=window_segments,
        )
