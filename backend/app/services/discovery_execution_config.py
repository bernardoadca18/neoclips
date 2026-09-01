"""Discovery execution config - runtime configuration from persisted DiscoveryRun.

This module provides typed runtime configuration objects reconstructed from
DiscoveryRun.config_snapshot, ensuring that worker processes use the exact
configuration that was persisted when the run was created.

This is critical for reproducibility: changing global defaults MUST NOT affect
already-created runs.
"""

import json
import logging
from dataclasses import dataclass
from hashlib import sha256

from app.prompts.clip_discovery_prompts import get_clip_discovery_prompt

logger = logging.getLogger(__name__)


class ExecutionConfigError(Exception):
    """Base error for execution config issues."""

    pass


class PromptNotFoundError(ExecutionConfigError):
    """Raised when prompt ID/version cannot be resolved."""

    pass


class PromptHashMismatchError(ExecutionConfigError):
    """Raised when runtime prompt hash doesn't match persisted hash."""

    pass


class UnsupportedVersionError(ExecutionConfigError):
    """Raised when scoring or dedup version is not supported."""

    pass


@dataclass(frozen=True)
class PromptConfig:
    """Prompt configuration with hash verification."""

    id: str
    version: str
    hash: str
    text: str


@dataclass(frozen=True)
class LLMConfig:
    """LLM provider configuration."""

    provider: str
    combo: str  # 9Router Combo alias
    temperature: float
    max_candidates_per_window: int


@dataclass(frozen=True)
class ScoringConfig:
    """Scoring algorithm configuration."""

    version: str


@dataclass(frozen=True)
class DedupConfig:
    """Deduplication configuration."""

    version: str
    iou_threshold: float


@dataclass(frozen=True)
class WindowConfig:
    """Window building configuration."""

    duration_seconds: float
    overlap_seconds: float


@dataclass(frozen=True)
class DiscoveryExecutionConfig:
    """Complete execution configuration reconstructed from persisted run.

    This config is immutable and captures all parameters that affect
    discovery output. Worker processes MUST use this config, not global defaults.
    """

    strategy_id: str
    strategy_version: str
    prompt: PromptConfig
    llm: LLMConfig
    window: WindowConfig
    scoring: ScoringConfig
    dedup: DedupConfig

    def verify_prompt_hash(self) -> None:
        """Verify that runtime prompt hash matches persisted hash.

        Raises:
            PromptHashMismatchError: If hashes don't match
        """
        computed_hash = sha256(self.prompt.text.encode()).hexdigest()
        if computed_hash != self.prompt.hash:
            raise PromptHashMismatchError(
                f"Prompt hash mismatch: computed {computed_hash[:16]}... "
                f"but persisted {self.prompt.hash[:16]}..."
            )

    def verify_supported_versions(self) -> None:
        """Verify that scoring and dedup versions are supported.

        Raises:
            UnsupportedVersionError: If unsupported version detected
        """
        supported_scoring = {"clip_score_v1"}
        if self.scoring.version not in supported_scoring:
            raise UnsupportedVersionError(
                f"Unsupported scoring version: {self.scoring.version}. "
                f"Supported: {supported_scoring}"
            )

        supported_dedup = {"temporal_iou_v1"}
        if self.dedup.version not in supported_dedup:
            raise UnsupportedVersionError(
                f"Unsupported dedup version: {self.dedup.version}. "
                f"Supported: {supported_dedup}"
            )


def parse_execution_config(config_snapshot: str) -> DiscoveryExecutionConfig:
    """Parse execution config from persisted JSON snapshot.

    Args:
        config_snapshot: JSON string from DiscoveryRun.config_snapshot

    Returns:
        DiscoveryExecutionConfig with verified configuration

    Raises:
        ExecutionConfigError: If config cannot be parsed or is invalid
        PromptNotFoundError: If prompt cannot be resolved
        PromptHashMismatchError: If prompt hash verification fails
        UnsupportedVersionError: If scoring/dedup version unsupported
    """
    try:
        data = json.loads(config_snapshot)
    except json.JSONDecodeError as e:
        raise ExecutionConfigError(f"Invalid config_snapshot JSON: {e}") from e

    try:
        # Parse prompt config
        prompt_data = data["prompt"]
        prompt_id = prompt_data["id"]
        prompt_version = prompt_data["version"]
        prompt_hash = prompt_data["hash"]

        # Resolve prompt text from registry
        prompt_text = get_clip_discovery_prompt(prompt_id, prompt_version)
        if prompt_text is None:
            raise PromptNotFoundError(
                f"Cannot resolve prompt {prompt_id}@{prompt_version}"
            )

        prompt = PromptConfig(
            id=prompt_id,
            version=prompt_version,
            hash=prompt_hash,
            text=prompt_text,
        )

        # Parse LLM config
        llm_data = data["llm"]
        llm = LLMConfig(
            provider=llm_data["provider"],
            combo=llm_data["model"],
            temperature=llm_data["temperature"],
            max_candidates_per_window=llm_data["max_candidates_per_window"],
        )

        # Parse window config
        window_data = data["window"]
        window = WindowConfig(
            duration_seconds=window_data["duration_seconds"],
            overlap_seconds=window_data["overlap_seconds"],
        )

        # Parse scoring config
        scoring_data = data["scoring"]
        scoring = ScoringConfig(version=scoring_data["version"])

        # Parse dedup config
        dedup_data = data["dedup"]
        dedup = DedupConfig(
            version=dedup_data["version"],
            iou_threshold=dedup_data["iou_threshold"],
        )

        # Build complete config
        config = DiscoveryExecutionConfig(
            strategy_id=data["strategy"]["id"],
            strategy_version=data["strategy"]["version"],
            prompt=prompt,
            llm=llm,
            window=window,
            scoring=scoring,
            dedup=dedup,
        )

        # Verify prompt hash
        config.verify_prompt_hash()

        # Verify supported versions
        config.verify_supported_versions()

        return config

    except KeyError as e:
        raise ExecutionConfigError(f"Missing required config field: {e}") from e


# Constants for execution bounds
MAX_WINDOW_ATTEMPTS = 3  # Maximum attempts before marking window as failed

SUPPORTED_SCORING_VERSIONS = {"clip_score_v1"}
SUPPORTED_DEDUP_VERSIONS = {"temporal_iou_v1"}


__all__ = [
    "DiscoveryExecutionConfig",
    "PromptConfig",
    "LLMConfig",
    "ScoringConfig",
    "DedupConfig",
    "WindowConfig",
    "parse_execution_config",
    "ExecutionConfigError",
    "PromptNotFoundError",
    "PromptHashMismatchError",
    "UnsupportedVersionError",
    "MAX_WINDOW_ATTEMPTS",
    "SUPPORTED_SCORING_VERSIONS",
    "SUPPORTED_DEDUP_VERSIONS",
]
