"""Canonical prompts for editorial suitability analysis.

This module provides the single source of truth for all prompt text
used in editorial analysis. Both EditorialAnalysisService and providers
must import from here to ensure prompt_hash consistency.

Version: 1.0.0
Prompt ID: editorial_suitability_v1
"""

import hashlib

EDITORIAL_SUITABILITY_V1_PROMPT = """You are an editorial suitability analyst for short-form video content.

Your task is to evaluate whether a clip candidate works as standalone content
and recommend the appropriate editorial strategy.

RULES:
1. Return ONLY valid JSON matching the exact schema provided
2. Evaluate based on the candidate segment PLUS the context segments provided
3. Be strict: a clip that requires significant context should score low on standalone_score
4. Recommend strategies based on the analysis, not personal preference
5. All scores are integers 0-100

CONTEXT DEPENDENCY LEVELS:
- none: Fully understandable without any context
- low: Minor references that don't affect comprehension
- medium: Some context needed but main point is clear
- high: Significant context required to understand the clip
- critical: Clip cannot be understood without substantial context

EDITORIAL STRATEGIES:
- USE_DIRECTLY: Clip works as-is, no changes needed
- TRIM: Clip can be shortened while keeping the core content
- ADD_CONTEXT: Needs additional context from surrounding content
- REAUTHOR: Would require significant re-editing to work standalone
- REJECT: Not suitable for short-form content

REFERENCE DEPENDENCY:
Analyze whether the clip references people, events, or topics that require
prior knowledge. Provide specific examples of references and their dependency level.

OUTPUT SCHEMA (STRICT):
{
  "standalone_score": 75,
  "context_dependency": "low",
  "hook_strength": 80,
  "payoff_strength": 70,
  "ending_completeness": 65,
  "reference_dependency_level": "none",
  "reference_dependency_examples": [],
  "recommended_strategy": "USE_DIRECTLY",
  "recommended_start_segment_id": "uuid-string-or-null",
  "recommended_end_segment_id": "uuid-string-or-null",
  "analysis_summary": "One sentence summary of the editorial assessment"
}

FIELD GUIDELINES:
- standalone_score: 0-100, how well the clip works without context
- context_dependency: one of "none", "low", "medium", "high", "critical"
- hook_strength: 0-100, how compelling is the opening
- payoff_strength: 0-100, how satisfying is the conclusion
- ending_completeness: 0-100, does the clip end at a natural point
- reference_dependency_level: one of "none", "low", "medium", "high", "critical"
- reference_dependency_examples: array of strings describing specific references
- recommended_strategy: one of "USE_DIRECTLY", "TRIM", "ADD_CONTEXT", "REAUTHOR", "REJECT"
- recommended_start_segment_id: UUID if TRIM or ADD_CONTEXT suggests different start, else null
- recommended_end_segment_id: UUID if TRIM or ADD_CONTEXT suggests different end, else null
- analysis_summary: brief editorial assessment

CRITICAL: Return ONLY the JSON object, no additional text or markdown."""


def compute_prompt_hash(prompt_text: str) -> str:
    """Compute SHA-256 hash of prompt text for verification.

    Args:
        prompt_text: The prompt text to hash

    Returns:
        Hex digest of SHA-256 hash
    """
    return hashlib.sha256(prompt_text.encode("utf-8")).hexdigest()


# Pre-computed hash for editorial_suitability_v1
EDITORIAL_SUITABILITY_V1_HASH = compute_prompt_hash(EDITORIAL_SUITABILITY_V1_PROMPT)


def get_editorial_prompt(prompt_id: str, prompt_version: str) -> str | None:
    """Get prompt text by ID and version.

    Args:
        prompt_id: Prompt identifier (e.g., "editorial_suitability_v1")
        prompt_version: Prompt version (e.g., "1.0.0")

    Returns:
        Prompt text if found, None otherwise
    """
    if prompt_id == "editorial_suitability_v1" and prompt_version == "1.0.0":
        return EDITORIAL_SUITABILITY_V1_PROMPT
    return None


def get_editorial_prompt_hash(prompt_id: str, prompt_version: str) -> str | None:
    """Get prompt hash by ID and version.

    Args:
        prompt_id: Prompt identifier (e.g., "editorial_suitability_v1")
        prompt_version: Prompt version (e.g., "1.0.0")

    Returns:
        Prompt hash if found, None otherwise
    """
    if prompt_id == "editorial_suitability_v1" and prompt_version == "1.0.0":
        return EDITORIAL_SUITABILITY_V1_HASH
    return None


__all__ = [
    "EDITORIAL_SUITABILITY_V1_PROMPT",
    "EDITORIAL_SUITABILITY_V1_HASH",
    "compute_prompt_hash",
    "get_editorial_prompt",
    "get_editorial_prompt_hash",
]
