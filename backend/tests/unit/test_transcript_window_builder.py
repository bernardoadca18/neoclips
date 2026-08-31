"""Unit tests for TranscriptWindowBuilder."""

from uuid import uuid4

from app.clients.media_indexer_client import TranscriptSegmentOut
from app.services.transcript_window_builder import (
    TranscriptWindow,
    TranscriptWindowBuilder,
    WindowConfig,
)


def make_segment(segment_id: str, start: float, end: float, text: str, sequence: int = 0) -> TranscriptSegmentOut:
    """Create a test transcript segment."""
    return TranscriptSegmentOut(
        id=uuid4(),
        transcription_id=uuid4(),
        sequence=sequence,
        start_seconds=start,
        end_seconds=end,
        text=text,
    )


class TestWindowConfig:
    """Tests for WindowConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = WindowConfig()
        assert config.window_duration_seconds == 300.0
        assert config.overlap_seconds == 60.0

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = WindowConfig(window_duration_seconds=600.0, overlap_seconds=120.0)
        assert config.window_duration_seconds == 600.0
        assert config.overlap_seconds == 120.0


class TestTranscriptWindowBuilder:
    """Tests for TranscriptWindowBuilder."""

    def test_build_empty_segments(self) -> None:
        """Test building windows from empty segment list."""
        builder = TranscriptWindowBuilder()
        windows = builder.build([])
        assert windows == []

    def test_build_single_window(self) -> None:
        """Test building a single window from short transcript."""
        builder = TranscriptWindowBuilder(WindowConfig(window_duration_seconds=300.0, overlap_seconds=60.0))
        segments = [
            make_segment("1", 0.0, 10.0, "Hello world"),
            make_segment("2", 10.0, 20.0, "This is a test"),
            make_segment("3", 20.0, 30.0, "End of transcript"),
        ]
        windows = builder.build(segments)

        assert len(windows) == 1
        assert windows[0].window_index == 0
        assert windows[0].start_seconds == 0.0
        assert windows[0].segment_count == 3

    def test_build_multiple_windows(self) -> None:
        """Test building multiple windows from longer transcript."""
        builder = TranscriptWindowBuilder(WindowConfig(window_duration_seconds=60.0, overlap_seconds=20.0))

        # Create 10 minutes of segments (600 seconds)
        segments = []
        for i in range(60):
            start = i * 10.0
            segments.append(make_segment(str(i), start, start + 10.0, f"Segment {i}"))

        windows = builder.build(segments)

        # Should have multiple windows with overlap
        assert len(windows) >= 2

        # Check window indices are sequential
        for i, window in enumerate(windows):
            assert window.window_index == i

    def test_window_overlap(self) -> None:
        """Test that windows have proper overlap."""
        builder = TranscriptWindowBuilder(WindowConfig(window_duration_seconds=60.0, overlap_seconds=20.0))

        segments = []
        for i in range(12):
            start = i * 10.0
            segments.append(make_segment(str(i), start, start + 10.0, f"Segment {i}"))

        windows = builder.build(segments)

        if len(windows) >= 2:
            # First window end should be after second window start (overlap)
            assert windows[0].end_seconds > windows[1].start_seconds

    def test_segments_assignment(self) -> None:
        """Test that segments are correctly assigned to windows."""
        builder = TranscriptWindowBuilder(WindowConfig(window_duration_seconds=30.0, overlap_seconds=10.0))

        segments = [
            make_segment("1", 0.0, 10.0, "First"),
            make_segment("2", 10.0, 20.0, "Second"),
            make_segment("3", 20.0, 30.0, "Third"),
        ]
        windows = builder.build(segments)

        assert len(windows) == 1
        assert len(windows[0].segments) == 3


class TestTranscriptWindow:
    """Tests for TranscriptWindow dataclass."""

    def test_transcript_window_creation(self) -> None:
        """Test creating a transcript window."""
        segments = [
            make_segment("1", 0.0, 10.0, "Hello"),
            make_segment("2", 10.0, 20.0, "World"),
        ]
        window = TranscriptWindow(
            window_index=0,
            start_seconds=0.0,
            end_seconds=300.0,
            segments=segments,
        )

        assert window.window_index == 0
        assert window.start_seconds == 0.0
        assert window.end_seconds == 300.0
        assert len(window.segments) == 2
        assert window.segment_count == 2

    def test_transcript_window_times(self) -> None:
        """Test transcript window time boundaries."""
        window = TranscriptWindow(
            window_index=0,
            start_seconds=0.0,
            end_seconds=300.0,
            segments=[],
        )

        assert window.end_seconds - window.start_seconds == 300.0
