"""Media Indexer transcript provider implementation."""

import logging
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

logger = logging.getLogger(__name__)


class MediaIndexerTranscriptProvider:
    """Transcript provider that fetches from Media Indexer.

    This implementation handles pagination automatically to ensure
    all transcript segments are retrieved, not just the first 500.

    Usage:
        provider = MediaIndexerTranscriptProvider(client)
        segments = await provider.get_transcript(source_id)
    """

    def __init__(self, client: MediaIndexerClient) -> None:
        self._client = client

    async def get_transcript(
        self,
        source_id: str,
    ) -> list[TranscriptSegmentOut]:
        """Get all transcript segments for a source.

        Uses get_all_transcript_segments which handles pagination
        automatically to fetch ALL segments, not just the first page.

        Args:
            source_id: The ClipSource ID (used to look up transcription_id)

        Returns:
            List of all transcript segments, sorted by start time

        Raises:
            TranscriptNotFoundError: If no transcript exists
            TranscriptProviderError: If retrieval fails
        """
        # Note: In production, we need to get the transcription_id from ClipSource
        # This is a simplified version that assumes source_id IS the transcription_id
        # The actual integration should resolve source_id -> transcription_id first
        try:
            # Use the pagination-aware method
            segments = await self._client.get_all_transcript_segments(
                transcription_id=UUID(source_id),
            )

            # Sort by start time
            segments.sort(key=lambda s: s.start_seconds)

            return segments

        except MediaIndexerAPIError as e:
            if e.status_code == 404:
                raise TranscriptNotFoundError(source_id)
            raise TranscriptProviderError(
                f"Media Indexer API error: {e.message}",
                source_id=source_id,
            )

    async def get_transcript_for_time_range(
        self,
        source_id: str,
        start_seconds: float,
        end_seconds: float,
    ) -> list[TranscriptSegmentOut]:
        """Get transcript segments for a specific time range.

        Fetches all segments and filters to the requested range.
        For very large transcripts, a more efficient implementation
        could use server-side filtering if Media Indexer supports it.

        Args:
            source_id: The source identifier
            start_seconds: Start of time range
            end_seconds: End of time range

        Returns:
            List of transcript segments overlapping the time range
        """
        all_segments = await self.get_transcript(source_id)

        # Filter segments that overlap with the time range
        return [
            seg
            for seg in all_segments
            if seg.start_seconds < end_seconds and seg.end_seconds > start_seconds
        ]


__all__ = ["MediaIndexerTranscriptProvider"]
