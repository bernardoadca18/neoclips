"""Editorial suitability analysis provider using 9Router gateway.

Provides LLM-based editorial analysis with strict JSON validation via HTTP.
The LLM evaluates clip candidates for standalone suitability and recommends
editorial strategies.

9Router is the sole LLM gateway for NeoClips. It handles:
- Combo-based model routing
- Fallback chains across providers
- Rate limiting and quota management
"""

import json
import logging
from dataclasses import dataclass

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.editorial import LLMEditorialAnalysisResponse
from app.prompts.editorial_prompts import (
    EDITORIAL_SUITABILITY_V1_PROMPT,
    EDITORIAL_SUITABILITY_V1_HASH,
    get_editorial_prompt,
    get_editorial_prompt_hash,
)

logger = logging.getLogger(__name__)


class NineRouterEditorialError(Exception):
    """Base error for 9Router editorial provider."""

    pass


class NineRouterEditorialUnavailableError(NineRouterEditorialError):
    """Raised when 9Router is unreachable."""

    pass


class NineRouterEditorialResponseError(NineRouterEditorialError):
    """Raised when 9Router returns an error response."""

    pass


class LLMEditorialValidationError(NineRouterEditorialError):
    """Raised when LLM response fails validation."""

    def __init__(self, message: str, raw_response: str | None = None) -> None:
        super().__init__(message)
        self.raw_response = raw_response


@dataclass
class EditorialProviderResult:
    """Result from editorial provider including resolved model info."""

    response: LLMEditorialAnalysisResponse
    raw_content: str
    requested_combo: str
    resolved_model: str | None = None
    prompt_hash: str | None = None


@dataclass
class CandidateContext:
    """Context for editorial analysis containing candidate and surrounding segments."""

    candidate_id: str
    candidate_segments: list[dict]  # List of segment dicts with id, start, end, text
    context_before_segments: list[dict]  # Segments before the candidate
    context_after_segments: list[dict]  # Segments after the candidate


class NineRouterEditorialProvider:
    """
    LLM-based editorial suitability provider using 9Router gateway.

    Sends candidate context to LLM for editorial analysis via 9Router.
    The LLM returns suitability scores and recommended editorial strategy.

    9Router handles:
    - Combo-based routing (logical role → physical model)
    - Fallback chains across multiple providers
    - Rate limiting and quota management

    Configuration:
        - combo: 9Router Combo alias (e.g., "neoclips-editorial")
        - base_url: 9Router gateway URL (default: from settings.nine_router_base_url)
        - api_key: API key for 9Router (default: from settings.nine_router_api_key)
        - timeout_seconds: Request timeout (default: from settings.nine_router_timeout_seconds)
        - system_prompt: Optional custom system prompt
    """

    def __init__(
        self,
        combo: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int | None = None,
        system_prompt: str | None = None,
        prompt_id: str = "editorial_suitability_v1",
        prompt_version: str = "1.0.0",
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> None:
        self.combo = combo or settings.nine_router_editorial_combo
        self.base_url = (base_url or settings.nine_router_base_url).rstrip("/")
        self.api_key = api_key or settings.nine_router_api_key
        self.timeout_seconds = timeout_seconds or settings.nine_router_timeout_seconds
        self.prompt_id = prompt_id
        self.prompt_version = prompt_version
        self._system_prompt = system_prompt
        self.temperature = temperature if temperature is not None else 0.3
        self.max_tokens = max_tokens if max_tokens is not None else 1500

    def _build_system_prompt(self) -> str:
        """Build the system prompt for editorial analysis."""
        if self._system_prompt:
            return self._system_prompt

        prompt = get_editorial_prompt(self.prompt_id, self.prompt_version)
        if prompt:
            return prompt

        # Fallback to canonical prompt
        return EDITORIAL_SUITABILITY_V1_PROMPT

    def _get_prompt_hash(self) -> str | None:
        """Get the hash for the current prompt configuration."""
        hash_value = get_editorial_prompt_hash(self.prompt_id, self.prompt_version)
        if hash_value:
            return hash_value
        return EDITORIAL_SUITABILITY_V1_HASH

    def _build_user_prompt(self, context: CandidateContext) -> str:
        """Build the user prompt with candidate and context segments."""
        lines = []

        # Add context before
        if context.context_before_segments:
            lines.append("=== CONTEXT BEFORE ===")
            for seg in context.context_before_segments:
                lines.append(f"[{seg['id']}] ({seg['start_seconds']:.1f}s - {seg['end_seconds']:.1f}s): {seg['text']}")
            lines.append("")

        # Add candidate segments
        lines.append("=== CANDIDATE SEGMENTS ===")
        for seg in context.candidate_segments:
            lines.append(f"[{seg['id']}] ({seg['start_seconds']:.1f}s - {seg['end_seconds']:.1f}s): {seg['text']}")
        lines.append("")

        # Add context after
        if context.context_after_segments:
            lines.append("=== CONTEXT AFTER ===")
            for seg in context.context_after_segments:
                lines.append(f"[{seg['id']}] ({seg['start_seconds']:.1f}s - {seg['end_seconds']:.1f}s): {seg['text']}")
            lines.append("")

        return f"""Analyze this clip candidate for editorial suitability.

CANDIDATE ID: {context.candidate_id}

{chr(10).join(lines)}

Evaluate whether the candidate works as standalone content and recommend an editorial strategy.
Return JSON with your analysis."""

    async def analyze_candidate(
        self, context: CandidateContext
    ) -> tuple[LLMEditorialAnalysisResponse, str]:
        """
        Analyze a candidate for editorial suitability.

        Args:
            context: Candidate context with segments

        Returns:
            Tuple of (validated response, raw LLM response)

        Raises:
            NineRouterEditorialUnavailableError: If 9Router is unreachable
            NineRouterEditorialResponseError: If 9Router returns an error
            LLMEditorialValidationError: If response cannot be parsed or validated
        """
        result = await self.analyze_candidate_with_model(context)
        return result.response, result.raw_content

    async def analyze_candidate_with_model(
        self, context: CandidateContext
    ) -> EditorialProviderResult:
        """
        Analyze candidate with resolved model information.

        Args:
            context: Candidate context with segments

        Returns:
            EditorialProviderResult with response, raw content, and model info

        Raises:
            NineRouterEditorialUnavailableError: If 9Router is unreachable
            NineRouterEditorialResponseError: If 9Router returns an error
            LLMEditorialValidationError: If response cannot be parsed or validated
        """
        messages = [
            {"role": "system", "content": self._build_system_prompt()},
            {"role": "user", "content": self._build_user_prompt(context)},
        ]

        payload = {
            "model": self.combo,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
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
                resolved_model = data.get("model")

                if not raw_content:
                    raise NineRouterEditorialResponseError("Empty response from 9Router")

                validated = self._validate_response(raw_content, context)

                return EditorialProviderResult(
                    response=validated,
                    raw_content=raw_content,
                    requested_combo=self.combo,
                    resolved_model=resolved_model,
                    prompt_hash=self._get_prompt_hash(),
                )

            except httpx.HTTPStatusError as e:
                logger.error(f"9Router HTTP error: {e.response.status_code} - {e.response.text}")
                raise NineRouterEditorialResponseError(
                    f"9Router HTTP error: {e.response.status_code}"
                ) from e
            except httpx.ConnectError as e:
                logger.error(f"9Router connection error: {e}")
                raise NineRouterEditorialUnavailableError(f"9Router unreachable: {e}") from e
            except httpx.TimeoutException as e:
                logger.error(f"9Router timeout: {e}")
                raise NineRouterEditorialUnavailableError(f"9Router timeout: {e}") from e
            except httpx.RequestError as e:
                logger.error(f"9Router request error: {e}")
                raise NineRouterEditorialUnavailableError(f"9Router request error: {e}") from e

    def _validate_response(
        self, raw_content: str, context: CandidateContext | None = None
    ) -> LLMEditorialAnalysisResponse:
        """
        Validate and parse LLM response.

        Args:
            raw_content: Raw string response from LLM
            context: Optional context for segment ID validation

        Returns:
            Validated LLMEditorialAnalysisResponse

        Raises:
            LLMEditorialValidationError: If validation fails
        """
        # Strip potential markdown code blocks
        content = raw_content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as e:
            raise LLMEditorialValidationError(
                f"Invalid JSON: {e}", raw_response=raw_content
            ) from e

        try:
            response = LLMEditorialAnalysisResponse(**parsed)
        except ValidationError as e:
            raise LLMEditorialValidationError(
                f"Schema validation failed: {e}", raw_response=raw_content
            ) from e

        # Validate segment IDs exist in context (if provided)
        if context is not None:
            all_segment_ids = set()
            for seg in context.candidate_segments:
                all_segment_ids.add(str(seg["id"]))
            for seg in context.context_before_segments:
                all_segment_ids.add(str(seg["id"]))
            for seg in context.context_after_segments:
                all_segment_ids.add(str(seg["id"]))

            if response.recommended_start_segment_id:
                if str(response.recommended_start_segment_id) not in all_segment_ids:
                    raise LLMEditorialValidationError(
                        f"recommended_start_segment_id {response.recommended_start_segment_id} not found in context",
                        raw_response=raw_content,
                    )
            if response.recommended_end_segment_id:
                if str(response.recommended_end_segment_id) not in all_segment_ids:
                    raise LLMEditorialValidationError(
                        f"recommended_end_segment_id {response.recommended_end_segment_id} not found in context",
                        raw_response=raw_content,
                    )

        return response


__all__ = [
    "NineRouterEditorialProvider",
    "NineRouterEditorialError",
    "NineRouterEditorialUnavailableError",
    "NineRouterEditorialResponseError",
    "LLMEditorialValidationError",
    "EditorialProviderResult",
    "CandidateContext",
]
