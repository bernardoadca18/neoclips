"""Media Indexer transcript provider implementation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from app.clients.media_indexer_client import (
    MediaIndexerAPIError,
    MediaIndexerClient,
    TranscriptSegmentOut,
)
from app.providers.exceptions import (
    TranscriptNotFoundError,
    TranscriptProviderError,
)

if TYPE_CHECKING:
    from app.clients.transcript_segment_stream import TranscriptSegmentStream

logger = logging.getLogger(__name__)


class MediaIndexerTranscriptProvider:
    """Transcript provider that fetches from Media Indexer.

    This implementation correctly resolves source_id to transcription_id
    and uses streaming for bounded memory usage on large transcripts.

    Usage:
        provider = MediaIndexerTranscriptProvider(client)
        segments = await provider.get_transcript(transcription_id)
    """

    def __init__(self, client: MediaIndexerClient) -> None:
        self._client = client

    async def get_transcript(
        self,
        transcription_id: str,
    ) -> list[TranscriptSegmentOut]:
        """Get all transcript segments for a transcription.

        Uses get_all_transcript_segments which handles pagination
        automatically to fetch ALL segments, not just the first page.

        WARNING: This loads all segments into memory. For large transcripts,
        use get_transcript_stream() instead for bounded memory usage.

        Args:
            transcription_id: The transcription UUID from Media Indexer

        Returns:
            List of all transcript segments, sorted by start time

        Raises:
            TranscriptNotFoundError: If no transcript exists
            TranscriptProviderError: If retrieval fails
        """
        try:
            segments = await self._client.get_all_transcript_segments(
                transcription_id=UUID(transcription_id),
            )

            segments.sort(key=lambda s: s.start_seconds)

            return segments

        except MediaIndexerAPIError as e:
            if e.status_code == 404:
                raise TranscriptNotFoundError(transcription_id)
            raise TranscriptProviderError(
                f"Media Indexer API error: {e.message}",
                source_id=transcription_id,
            )

    async def get_transcript_stream(
        self,
        transcription_id: str,
        page_size: int = 500,
    ) -> TranscriptSegmentStream:
        """Get a streaming transcript iterator for bounded memory usage.

        This is the recommended method for production use with large
        transcripts. It returns an async iterator that fetches pages
        lazily, keeping memory usage O(page_size).

        Args:
            transcription_id: The transcription UUID from Media Indexer
            page_size: Number of segments per page (default 500)

        Returns:
            TranscriptSegmentStream async iterator

        Raises:
            TranscriptNotFoundError: If no transcript exists
            TranscriptProviderError: If retrieval fails
        """
        from app.clients.transcript_segment_stream import TranscriptSegmentStream

        return TranscriptSegmentStream(
            client=self._client,
            transcription_id=UUID(transcription_id),
            page_size=page_size,
        )

    async def get_transcript_for_time_range(
        self,
        transcription_id: str,
        start_seconds: float,
        end_seconds: float,
    ) -> list[TranscriptSegmentOut]:
        """Get transcript segments for a specific time range.

        Uses streaming to fetch only segments needed for the window,
        stopping when we've passed the end of the time range.

        Args:
            transcription_id: The transcription UUID
            start_seconds: Start of time range
            end_seconds: End of time range

        Returns:
            List of transcript segments overlapping the time range
        """
        stream = await self.get_transcript_stream(transcription_id)
        result: list[TranscriptSegmentOut] = await stream.fetch_all_for_window(
            window_start_seconds=start_seconds,
            window_end_seconds=end_seconds,
        )
        return result


__all__ = ["MediaIndexerTranscriptProvider"]
