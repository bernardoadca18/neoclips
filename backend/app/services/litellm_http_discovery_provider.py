"""ClipDiscoveryProvider using LiteLLM HTTP proxy for clip discovery.

Provides LLM-based clip discovery with strict JSON validation via HTTP.
The LLM acts as a semantic judge, returning segment IDs that are
later canonicalized to trusted timestamps.
"""

import json
import logging

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.discovery import LLMDiscoveryResponse
from app.services.clip_discovery_protocol import (
    ClipDiscoveryProvider as ClipDiscoveryProviderProtocol,
)
from app.services.transcript_window_builder import TranscriptWindow

logger = logging.getLogger(__name__)


class ClipDiscoveryProviderError(Exception):
    """Base error for clip discovery provider."""

    pass


class LLMResponseValidationError(ClipDiscoveryProviderError):
    """Raised when LLM response fails validation."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


class LiteLLMHTTPDiscoveryProvider(ClipDiscoveryProviderProtocol):
    """
    LLM-based clip discovery provider using LiteLLM HTTP proxy.

    Sends transcript windows to LLM for clip candidate discovery via HTTP.
    The LLM returns segment IDs (not timestamps) for clip boundaries.
    The CandidateCanonicalizer later resolves these to trusted timestamps.

    Configuration:
        - model: LLM model identifier (e.g., "openai/gpt-4o", "anthropic/claude-3-sonnet")
        - base_url: LiteLLM proxy URL (default: from settings.litellm_base_url)
        - api_key: API key for LiteLLM proxy (default: from settings.litellm_api_key)
        - max_candidates_per_window: Maximum candidates per window (default: 10)
        - temperature: Sampling temperature (default: 0.3 for consistency)
    """

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        base_url: str | None = None,
        api_key: str | None = None,
        max_candidates_per_window: int = 10,
        temperature: float = 0.3,
        timeout_seconds: int | None = None,
    ) -> None:
        self.model = model
        self.base_url = (base_url or settings.litellm_base_url).rstrip("/")
        self.api_key = api_key or settings.litellm_api_key
        self.max_candidates_per_window = max_candidates_per_window
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds or settings.litellm_timeout_seconds

    def _build_system_prompt(self) -> str:
        """Build the system prompt for clip discovery."""
        return """You are a clip discovery assistant for video content.

Your task is to identify compelling clip candidates from transcript segments.

RULES:
1. Return ONLY valid JSON matching the exact schema provided
2. Each clip MUST have start_segment_id and end_segment_id from the provided segments
3. Clips should be 15-180 seconds in duration
4. Focus on segments with clear narrative hooks: questions, revelations, emotional moments
5. Provide descriptive titles and summaries
6. Identify hook types: "question", "statement", "story", "revelation", "emotional", "humor"
7. Maximum 10 clips per window
8. Return {"clips": []} if no good candidates found

HOOK TYPES:
- question: Poses an intriguing question
- statement: Makes a bold or surprising claim
- story: Begins a narrative arc
- revelation: Reveals new information
- emotional: Contains emotional resonance
- humor: Contains comedic potential

SEMANTIC FEATURES (rate each 0.0 to 1.0):
- hook_strength: How strong is the opening hook? (0=weak, 1=very strong)
- standalone_clarity: Can this clip be understood without context? (0=needs context, 1=fully standalone)
- narrative_completeness: Does the clip have a complete arc? (0=incomplete, 1=complete story)
- emotional_intensity: How emotionally engaging is the content? (0=neutral, 1=very intense)
- topic_relevance: How relevant to the main topic? (0=tangent, 1=core topic)

OUTPUT SCHEMA (STRICT):
{
  "clips": [
    {
      "start_segment_id": "uuid-string",
      "end_segment_id": "uuid-string",
      "title": "Brief compelling title",
      "summary": "One sentence summary",
      "hook_type": "one of the hook types",
      "hook_description": "Why this makes a good clip",
      "hook_strength": 0.8,
      "standalone_clarity": 0.9,
      "narrative_completeness": 0.7,
      "emotional_intensity": 0.5,
      "topic_relevance": 0.9
    }
  ]
}

CRITICAL: Return ONLY the JSON object, no additional text or markdown."""

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
            ClipDiscoveryProviderError: If HTTP request fails
            LLMResponseValidationError: If response cannot be parsed or validated
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_prompt(window)},
        ]

        payload = {
            "model": self.model,
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

                if not raw_content:
                    raise ClipDiscoveryProviderError("Empty response from LLM")

                validated = self._validate_response(raw_content, window)
                return validated, raw_content

            except httpx.HTTPStatusError as e:
                logger.error(f"LiteLLM HTTP error: {e.response.status_code} - {e.response.text}")
                raise ClipDiscoveryProviderError(
                    f"LiteLLM HTTP error: {e.response.status_code}"
                ) from e
            except httpx.RequestError as e:
                logger.error(f"LiteLLM request error: {e}")
                raise ClipDiscoveryProviderError(f"LiteLLM request error: {e}") from e

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
