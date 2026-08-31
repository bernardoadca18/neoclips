"""ClipDiscoveryProvider protocol for dependency inversion.

Defines the interface for LLM-based clip discovery, allowing different
implementations (LiteLLM HTTP, mock, file-based) without tight coupling.
"""

from typing import Protocol

from app.schemas.discovery import LLMDiscoveryResponse
from app.services.transcript_window_builder import TranscriptWindow

__all__ = ["ClipDiscoveryProvider"]


class ClipDiscoveryProvider(Protocol):
    """Protocol for LLM-based clip discovery.

    Implementations must analyze transcript windows and return
    clip candidates with semantic features.

    This abstraction allows:
    - LiteLLM HTTP proxy (production)
    - Mock providers (testing)
    - File-based providers (evaluation)
    """

    async def discover_clips(
        self,
        window: TranscriptWindow,
    ) -> tuple[LLMDiscoveryResponse, str]:
        """Discover clip candidates from a transcript window.

        Args:
            window: Transcript window with segments to analyze

        Returns:
            Tuple of (parsed response, raw LLM response text)

        Raises:
            ClipDiscoveryProviderError: If discovery fails
        """
        ...
