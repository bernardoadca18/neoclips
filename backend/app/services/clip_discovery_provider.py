"""ClipDiscoveryProvider using LiteLLM for clip discovery.

Provides LLM-based clip discovery with strict JSON validation.
The LLM acts as a semantic judge, returning segment IDs that are
later canonicalized to trusted timestamps.
"""

import json
import logging
from typing import Any

from pydantic import ValidationError

from app.schemas.discovery import LLMClipSuggestion, LLMDiscoveryResponse
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


class ClipDiscoveryProvider:
    """
    LLM-based clip discovery provider using LiteLLM.

    Sends transcript windows to LLM for clip candidate discovery.
    The LLM returns segment IDs (not timestamps) for clip boundaries.
    The CandidateCanonicalizer later resolves these to trusted timestamps.

    Configuration:
        - model: LLM model identifier (e.g., "openai/gpt-4o", "anthropic/claude-3-sonnet")
        - max_candidates_per_window: Maximum candidates per window (default: 10)
        - temperature: Sampling temperature (default: 0.3 for consistency)
    """

    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        max_candidates_per_window: int = 10,
        temperature: float = 0.3,
    ) -> None:
        self.model = model
        self.max_candidates_per_window = max_candidates_per_window
        self.temperature = temperature

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

OUTPUT SCHEMA (STRICT):
{
  "clips": [
    {
      "start_segment_id": "uuid-string",
      "end_segment_id": "uuid-string",
      "title": "Brief compelling title",
      "summary": "One sentence summary",
      "hook_type": "one of the hook types",
      "hook_description": "Why this makes a good clip"
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
            LLMResponseValidationError: If response cannot be parsed or validated
        """
        try:
            import litellm
        except ImportError as e:
            raise ClipDiscoveryProviderError(
                "litellm not installed. Install with: pip install litellm"
            ) from e

        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_prompt(window)},
        ]

        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=2000,
            )

            raw_content = response.choices[0].message.content or ""
            validated = self._validate_response(raw_content, window)

            return validated, raw_content

        except litellm.exceptions.APIError as e:
            logger.error(f"LLM API error: {e}")
            raise ClipDiscoveryProviderError(f"LLM API error: {e}") from e

    def _validate_response(self, raw_content: str, window: TranscriptWindow | None = None) -> LLMDiscoveryResponse:
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
