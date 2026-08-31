"""Streaming transcript segment iterator for bounded-memory processing.

This module provides an async generator-based approach to transcript
pagination that never loads all segments into memory at once. Instead,
it fetches pages incrementally and yields them for processing.

This is critical for production discovery pipelines that must handle
transcripts with tens of thousands of segments without OOM errors.

Usage:
    client = MediaIndexerClient()
    stream = TranscriptSegmentStream(client, transcription_id)

    async for page in stream:
        # Process page.items (bounded batch)
        # After processing, page.items goes out of scope
        pass

    # Or with window-aware processing:
    async for page in stream:
        segments_for_window = filter_to_window(page.items, window)
        # Process only what's needed
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import UUID

from app.clients.media_indexer_client import (
    MediaIndexerClient,
    TranscriptSegmentOut,
)

logger = logging.getLogger(__name__)


@dataclass
class TranscriptSegmentPage:
    """A page of transcript segments with metadata."""

    items: list[TranscriptSegmentOut]
    offset: int
    total: int
    page_number: int
    has_more: bool


class TranscriptSegmentStream:
    """Async iterator for transcript segments with bounded memory.

    This class implements the streaming pattern required for production
    discovery pipelines. It never accumulates all segments in memory;
    instead, it fetches pages one at a time and yields them for processing.

    Key properties:
    - Memory usage is O(page_size), not O(total_segments)
    - Pages are fetched lazily (only when needed)
    - The caller controls when to advance to the next page
    - Safe for transcripts with 50,000+ segments

    Example:
        stream = TranscriptSegmentStream(client, transcription_id, page_size=500)

        async for page in stream:
            # Process page.items
            for segment in page.items:
                # Do something with segment
                pass
            # page.items goes out of scope here, freeing memory
    """

    def __init__(
        self,
        client: MediaIndexerClient,
        transcription_id: UUID,
        page_size: int = 500,
    ) -> None:
        """Initialize the stream.

        Args:
            client: MediaIndexerClient instance
            transcription_id: UUID of the transcription
            page_size: Number of segments per page (default 500)
        """
        self._client = client
        self._transcription_id = transcription_id
        self._page_size = page_size
        self._offset = 0
        self._total: int | None = None
        self._page_number = 0
        self._exhausted = False

    @property
    def total_segments(self) -> int | None:
        """Return total segment count if known (after first fetch)."""
        return self._total

    @property
    def page_size(self) -> int:
        """Return the configured page size."""
        return self._page_size

    def __aiter__(self) -> AsyncIterator[TranscriptSegmentPage]:
        """Return self as async iterator."""
        return self

    async def __anext__(self) -> TranscriptSegmentPage:
        """Fetch and return the next page of segments.

        Raises:
            StopAsyncIteration: When all segments have been fetched
            MediaIndexerAPIError: If the API returns an error
        """
        if self._exhausted:
            raise StopAsyncIteration

        # Fetch the next page
        page = await self._client.get_transcript_segments(
            transcription_id=self._transcription_id,
            offset=self._offset,
            limit=self._page_size,
        )

        # Store total on first fetch
        if self._total is None:
            self._total = page.total
            logger.info(
                "transcript_stream_started",
                extra={
                    "transcription_id": str(self._transcription_id),
                    "total_segments": page.total,
                    "page_size": self._page_size,
                },
            )

        # Check if we've fetched all segments
        has_more = self._offset + len(page.items) < page.total

        # Create the page result
        result = TranscriptSegmentPage(
            items=page.items,
            offset=self._offset,
            total=page.total,
            page_number=self._page_number,
            has_more=has_more,
        )

        # Update state for next iteration
        self._offset += len(page.items)
        self._page_number += 1

        # Check if exhausted
        if not has_more or len(page.items) == 0:
            self._exhausted = True
            logger.info(
                "transcript_stream_complete",
                extra={
                    "transcription_id": str(self._transcription_id),
                    "total_fetched": self._offset,
                    "pages_fetched": self._page_number,
                },
            )

        return result

    async def fetch_all_for_window(
        self,
        window_start_seconds: float,
        window_end_seconds: float,
    ) -> list[TranscriptSegmentOut]:
        """Fetch segments for a specific time window.

        This method fetches pages until it has all segments for the
        specified time window. It's more efficient than loading all
        segments when you only need a subset.

        WARNING: This still loads all segments for the window into memory.
        Use only when the window is bounded and reasonably sized.

        Args:
            window_start_seconds: Start time of the window
            window_end_seconds: End time of the window

        Returns:
            List of segments overlapping the time window
        """
        window_segments: list[TranscriptSegmentOut] = []
        found_start = False

        async for page in self:
            for segment in page.items:
                # Check if segment overlaps with window
                if segment.start_seconds < window_end_seconds and segment.end_seconds > window_start_seconds:
                    window_segments.append(segment)
                    found_start = True
                elif found_start and segment.start_seconds >= window_end_seconds:
                    # We've passed the window, stop fetching
                    return window_segments

        return window_segments

    @staticmethod
    def filter_segments_for_window(
        segments: list[TranscriptSegmentOut],
        window_start_seconds: float,
        window_end_seconds: float,
    ) -> list[TranscriptSegmentOut]:
        """Filter segments to those overlapping a time window.

        This is a pure function that can be used on any segment list
        without fetching from the API.

        Args:
            segments: List of segments to filter
            window_start_seconds: Start time of the window
            window_end_seconds: End time of the window

        Returns:
            List of segments overlapping the time window
        """
        return [
            seg
            for seg in segments
            if seg.start_seconds < window_end_seconds and seg.end_seconds > window_start_seconds
        ]


async def stream_transcript_segments(
    client: MediaIndexerClient,
    transcription_id: UUID,
    page_size: int = 500,
) -> AsyncIterator[TranscriptSegmentPage]:
    """Convenience function to create and iterate a stream.

    Args:
        client: MediaIndexerClient instance
        transcription_id: UUID of the transcription
        page_size: Number of segments per page

    Yields:
        TranscriptSegmentPage objects
    """
    stream = TranscriptSegmentStream(client, transcription_id, page_size)
    async for page in stream:
        yield page


__all__ = [
    "TranscriptSegmentStream",
    "TranscriptSegmentPage",
    "stream_transcript_segments",
]
