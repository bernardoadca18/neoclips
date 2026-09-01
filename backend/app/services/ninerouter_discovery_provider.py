"""ClipDiscoveryProvider using 9Router gateway for clip discovery.

Provides LLM-based clip discovery with strict JSON validation via HTTP.
The LLM acts as a semantic judge, returning segment IDs that are
later canonicalized to trusted timestamps.

9Router is the sole LLM gateway for NeoClips. It handles:
- Combo-based model routing
- Fallback chains across providers
- Rate limiting and quota management

NeoClips only needs to specify the logical role (discovery) and
the 9Router Combo alias handles physical model selection.
"""

import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.discovery import LLMDiscoveryResponse
from app.services.clip_discovery_protocol import (
    ClipDiscoveryProvider as ClipDiscoveryProviderProtocol,
)
from app.services.transcript_window_builder import TranscriptWindow

logger = logging.getLogger(__name__)


class NineRouterError(Exception):
    """Base error for 9Router provider."""

    pass


class NineRouterUnavailableError(NineRouterError):
    """Raised when 9Router is unreachable."""

    pass


class NineRouterResponseError(NineRouterError):
    """Raised when 9Router returns an error response."""

    pass


class LLMResponseValidationError(NineRouterError):
    """Raised when LLM response fails validation."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class DiscoveryProviderResult:
    """Result from discovery provider including resolved model info."""

    response: LLMDiscoveryResponse
    raw_content: str
    requested_combo: str
    resolved_model: str | None = None


class NineRouterDiscoveryProvider(ClipDiscoveryProviderProtocol):
    """
    LLM-based clip discovery provider using 9Router gateway.

    Sends transcript windows to LLM for clip candidate discovery via 9Router.
    The LLM returns segment IDs (not timestamps) for clip boundaries.
    The CandidateCanonicalizer later resolves these to trusted timestamps.

    9Router handles:
    - Combo-based routing (logical role → physical model)
    - Fallback chains across multiple providers
    - Rate limiting and quota management

    Configuration:
        - combo: 9Router Combo alias (e.g., "neoclips-discovery")
        - base_url: 9Router gateway URL (default: from settings.nine_router_base_url)
        - api_key: API key for 9Router (default: from settings.nine_router_api_key)
        - max_candidates_per_window: Maximum candidates per window (default: 10)
        - temperature: Sampling temperature (default: 0.3 for consistency)
    """

    def __init__(
        self,
        combo: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        max_candidates_per_window: int = 10,
        temperature: float = 0.3,
        timeout_seconds: int | None = None,
        system_prompt: str | None = None,
    ) -> None:
        self.combo = combo or settings.nine_router_discovery_combo
        self.base_url = (base_url or settings.nine_router_base_url).rstrip("/")
        self.api_key = api_key or settings.nine_router_api_key
        self.max_candidates_per_window = max_candidates_per_window
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds or settings.nine_router_timeout_seconds
        self.system_prompt = system_prompt

    def _build_system_prompt(self) -> str:
        """Build the system prompt for clip discovery.

        Uses runtime-provided prompt from execution config (verified against
        persisted prompt_hash) or falls back to canonical prompt from registry.
        """
        if self.system_prompt:
            # Runtime prompt from config_snapshot (verified by parse_execution_config)
            return self.system_prompt

        # Fallback to canonical prompt (for backward compatibility)
        from app.prompts.clip_discovery_prompts import CLIP_DISCOVERY_V1_PROMPT

        return CLIP_DISCOVERY_V1_PROMPT

    def _build_user_prompt(self, window: TranscriptWindow) -> str:
        """Build the user prompt with transcript segments."""
        segments_text = []
        for seg in window.segments:
            segments_text.append(
                f"[{seg.id}] ({seg.start_seconds:.1f}s - {seg.end_seconds:.1f}s): {seg.text}"
            )

        return f"""Analyze these transcript segments and identify compelling clip candidates.

TRANSCRIPT SEGMENTS (window: {window.start_seconds:.1f}s - {window.end_seconds:.1f}s):
{chr(10).join(segments_text)}

Return JSON with clips array (max {self.max_candidates_per_window} clips)."""

    async def discover_clips(
        self, window: TranscriptWindow
    ) -> tuple[LLMDiscoveryResponse, str]:
        """
        Discover clip candidates from a transcript window.

        Args:
            window: Transcript window to analyze

        Returns:
            Tuple of (validated response, raw LLM response)

        Raises:
            NineRouterUnavailableError: If 9Router is unreachable
            NineRouterResponseError: If 9Router returns an error
            LLMResponseValidationError: If response cannot be parsed or validated
        """
        result = await self.discover_clips_with_model(window)
        return result.response, result.raw_content

    async def discover_clips_with_model(
        self, window: TranscriptWindow
    ) -> DiscoveryProviderResult:
        """
        Discover clip candidates with resolved model information.

        Args:
            window: Transcript window to analyze

        Returns:
            DiscoveryProviderResult with response, raw content, and model info

        Raises:
            NineRouterUnavailableError: If 9Router is unreachable
            NineRouterResponseError: If 9Router returns an error
            LLMResponseValidationError: If response cannot be parsed or validated
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_prompt(window)},
        ]

        # The 'model' field contains the Combo alias
        payload = {
            "model": self.combo,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": 2000,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()

                data = response.json()
                raw_content = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                # Capture the actual resolved model from 9Router response
                resolved_model = data.get("model")

                if not raw_content:
                    raise NineRouterResponseError("Empty response from 9Router")

                validated = self._validate_response(raw_content, window)

                return DiscoveryProviderResult(
                    response=validated,
                    raw_content=raw_content,
                    requested_combo=self.combo,
                    resolved_model=resolved_model,
                )

            except httpx.HTTPStatusError as e:
                logger.error(f"9Router HTTP error: {e.response.status_code} - {e.response.text}")
                raise NineRouterResponseError(
                    f"9Router HTTP error: {e.response.status_code}"
                ) from e
            except httpx.ConnectError as e:
                logger.error(f"9Router connection error: {e}")
                raise NineRouterUnavailableError(f"9Router unreachable: {e}") from e
            except httpx.TimeoutException as e:
                logger.error(f"9Router timeout: {e}")
                raise NineRouterUnavailableError(f"9Router timeout: {e}") from e
            except httpx.RequestError as e:
                logger.error(f"9Router request error: {e}")
                raise NineRouterUnavailableError(f"9Router request error: {e}") from e

    def _validate_response(
        self, raw_content: str, window: TranscriptWindow | None = None
    ) -> LLMDiscoveryResponse:
        """
        Validate and parse LLM response.

        Args:
            raw_content: Raw string response from LLM
            window: Optional window for segment ID validation

        Returns:
            Validated LLMDiscoveryResponse

        Raises:
            LLMResponseValidationError: If validation fails
        """
        # Strip potential markdown code blocks
        content = raw_content.strip()
        if content.startswith("```"):
            # Remove markdown code block markers
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMResponseValidationError(
                f"Invalid JSON: {e}", raw_response=raw_content
            ) from e

        try:
            response = LLMDiscoveryResponse(**parsed)
        except ValidationError as e:
            raise LLMResponseValidationError(
                f"Schema validation failed: {e}", raw_response=raw_content
            ) from e

        # Validate segment IDs exist in the window (if provided)
        if window is not None:
            segment_ids = {str(seg.id) for seg in window.segments}
            for clip in response.clips:
                if str(clip.start_segment_id) not in segment_ids:
                    raise LLMResponseValidationError(
                        f"start_segment_id {clip.start_segment_id} not found in window",
                        raw_response=raw_content,
                    )
                if str(clip.end_segment_id) not in segment_ids:
                    raise LLMResponseValidationError(
                        f"end_segment_id {clip.end_segment_id} not found in window",
                        raw_response=raw_content,
                    )

        return response


# Legacy alias for backward compatibility during migration
ClipDiscoveryProviderError = NineRouterError


__all__ = [
    "NineRouterDiscoveryProvider",
    "NineRouterError",
    "NineRouterUnavailableError",
    "NineRouterResponseError",
    "LLMResponseValidationError",
    "DiscoveryProviderResult",
    "ClipDiscoveryProviderError",  # Legacy alias
]
