"""TranscriptProvider protocol for dependency inversion.

Defines the interface for transcript retrieval, allowing different
implementations (Media Indexer, mock, file-based) without tight coupling.
"""

from typing import Protocol

from app.clients.media_indexer_client import TranscriptSegmentOut
from app.providers.exceptions import (
    TranscriptNotFoundError,
    TranscriptProviderError,
)

__all__ = [
    "TranscriptProvider",
    "TranscriptNotFoundError",
    "TranscriptProviderError",
]


class TranscriptProvider(Protocol):
    """Protocol for transcript retrieval.

    Implementations must provide transcript segments for a given source.
    This abstraction allows:
    - Media Indexer HTTP client (production)
    - Mock providers (testing)
    - File-based providers (evaluation)
    """

    async def get_transcript(
        self,
        source_id: str,
    ) -> list[TranscriptSegmentOut]:
        """Get all transcript segments for a source.

        Args:
            source_id: The source identifier

        Returns:
            List of all transcript segments, sorted by start time

        Raises:
            TranscriptNotFoundError: If no transcript exists
            TranscriptProviderError: If retrieval fails
        """
        ...

    async def get_transcript_for_time_range(
        self,
        source_id: str,
        start_seconds: float,
        end_seconds: float,
    ) -> list[TranscriptSegmentOut]:
        """Get transcript segments for a specific time range.

        Args:
            source_id: The source identifier
            start_seconds: Start of time range
            end_seconds: End of time range

        Returns:
            List of transcript segments overlapping the time range
        """
        ...
