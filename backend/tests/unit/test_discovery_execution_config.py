"""Unit tests for discovery_execution_config module.

Tests cover:
- Valid config parsing
- Invalid JSON handling
- Missing required fields
- Unsupported scoring/dedup versions
- Prompt hash verification (mismatch and match)
- Prompt not found in registry
- Immutable dataclasses (frozen=True)
"""

import json
from hashlib import sha256

import pytest

from app.prompts.clip_discovery_prompts import get_clip_discovery_prompt
from app.services.discovery_execution_config import (
    MAX_WINDOW_ATTEMPTS,
    SUPPORTED_DEDUP_VERSIONS,
    SUPPORTED_SCORING_VERSIONS,
    DiscoveryExecutionConfig,
    ExecutionConfigError,
    LLMConfig,
    PromptConfig,
    PromptHashMismatchError,
    PromptNotFoundError,
    UnsupportedVersionError,
    WindowConfig,
    parse_execution_config,
)


@pytest.fixture
def valid_config_dict():
    """Create a valid config dictionary for testing."""
    # Get the actual prompt and compute its hash
    prompt_text = get_clip_discovery_prompt("clip_discovery_v1", "1.0.0")
    assert prompt_text is not None, "Prompt must exist in registry"
    prompt_hash = sha256(prompt_text.encode()).hexdigest()

    return {
        "strategy": {"id": "transcript_v1", "version": "1.0.0"},
        "prompt": {
            "id": "clip_discovery_v1",
            "version": "1.0.0",
            "hash": prompt_hash,
        },
        "llm": {
            "provider": "9router",
            "model": "neoclips-discovery",
            "temperature": 0.3,
            "max_candidates_per_window": 10,
        },
        "window": {
            "duration_seconds": 300,
            "overlap_seconds": 60,
        },
        "scoring": {"version": "clip_score_v1"},
        "dedup": {
            "version": "temporal_iou_v1",
            "iou_threshold": 0.5,
        },
    }


class TestParseExecutionConfig:
    """Tests for parse_execution_config function."""

    def test_valid_config_parsing(self, valid_config_dict):
        """Valid config parses successfully."""
        config_snapshot = json.dumps(valid_config_dict)
        config = parse_execution_config(config_snapshot)

        assert isinstance(config, DiscoveryExecutionConfig)
        assert config.strategy_id == "transcript_v1"
        assert config.strategy_version == "1.0.0"
        assert config.prompt.id == "clip_discovery_v1"
        assert config.llm.combo == "neoclips-discovery"
        assert config.window.duration_seconds == 300
        assert config.scoring.version == "clip_score_v1"
        assert config.dedup.iou_threshold == 0.5

    def test_invalid_json_raises_error(self):
        """Invalid JSON raises ExecutionConfigError."""
        with pytest.raises(ExecutionConfigError) as exc_info:
            parse_execution_config("not valid json")

        assert "Invalid config_snapshot JSON" in str(exc_info.value)

    def test_missing_strategy_raises_error(self, valid_config_dict):
        """Missing strategy field raises ExecutionConfigError."""
        del valid_config_dict["strategy"]
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(ExecutionConfigError) as exc_info:
            parse_execution_config(config_snapshot)

        assert "Missing required config field" in str(exc_info.value)

    def test_missing_prompt_raises_error(self, valid_config_dict):
        """Missing prompt field raises ExecutionConfigError."""
        del valid_config_dict["prompt"]
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(ExecutionConfigError) as exc_info:
            parse_execution_config(config_snapshot)

        assert "Missing required config field" in str(exc_info.value)

    def test_missing_llm_raises_error(self, valid_config_dict):
        """Missing llm field raises ExecutionConfigError."""
        del valid_config_dict["llm"]
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(ExecutionConfigError):
            parse_execution_config(config_snapshot)

    def test_missing_window_raises_error(self, valid_config_dict):
        """Missing window field raises ExecutionConfigError."""
        del valid_config_dict["window"]
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(ExecutionConfigError):
            parse_execution_config(config_snapshot)

    def test_missing_scoring_raises_error(self, valid_config_dict):
        """Missing scoring field raises ExecutionConfigError."""
        del valid_config_dict["scoring"]
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(ExecutionConfigError):
            parse_execution_config(config_snapshot)

    def test_missing_dedup_raises_error(self, valid_config_dict):
        """Missing dedup field raises ExecutionConfigError."""
        del valid_config_dict["dedup"]
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(ExecutionConfigError):
            parse_execution_config(config_snapshot)


class TestPromptResolution:
    """Tests for prompt resolution and hash verification."""

    def test_prompt_not_found_raises_error(self, valid_config_dict):
        """Non-existent prompt ID raises PromptNotFoundError."""
        valid_config_dict["prompt"]["id"] = "nonexistent_prompt"
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(PromptNotFoundError) as exc_info:
            parse_execution_config(config_snapshot)

        assert "Cannot resolve prompt" in str(exc_info.value)

    def test_prompt_hash_mismatch_raises_error(self, valid_config_dict):
        """Wrong prompt hash raises PromptHashMismatchError."""
        valid_config_dict["prompt"]["hash"] = "0" * 64  # Wrong hash
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(PromptHashMismatchError) as exc_info:
            parse_execution_config(config_snapshot)

        assert "Prompt hash mismatch" in str(exc_info.value)

    def test_prompt_hash_verified_on_parse(self, valid_config_dict):
        """Prompt hash is verified during parsing."""
        # This should succeed - hash is correct
        config_snapshot = json.dumps(valid_config_dict)
        config = parse_execution_config(config_snapshot)

        # Verify the hash matches
        computed = sha256(config.prompt.text.encode()).hexdigest()
        assert computed == config.prompt.hash


class TestVersionSupport:
    """Tests for scoring and dedup version support."""

    def test_unsupported_scoring_version_raises_error(self, valid_config_dict):
        """Unsupported scoring version raises UnsupportedVersionError."""
        valid_config_dict["scoring"]["version"] = "unknown_scoring_v1"
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(UnsupportedVersionError) as exc_info:
            parse_execution_config(config_snapshot)

        assert "Unsupported scoring version" in str(exc_info.value)

    def test_unsupported_dedup_version_raises_error(self, valid_config_dict):
        """Unsupported dedup version raises UnsupportedVersionError."""
        valid_config_dict["dedup"]["version"] = "unknown_dedup_v1"
        config_snapshot = json.dumps(valid_config_dict)

        with pytest.raises(UnsupportedVersionError) as exc_info:
            parse_execution_config(config_snapshot)

        assert "Unsupported dedup version" in str(exc_info.value)

    def test_supported_scoring_versions_constant(self):
        """SUPPORTED_SCORING_VERSIONS contains expected versions."""
        assert "clip_score_v1" in SUPPORTED_SCORING_VERSIONS

    def test_supported_dedup_versions_constant(self):
        """SUPPORTED_DEDUP_VERSIONS contains expected versions."""
        assert "temporal_iou_v1" in SUPPORTED_DEDUP_VERSIONS


class TestDataclassImmutability:
    """Tests for frozen dataclass behavior."""

    def test_config_is_frozen(self, valid_config_dict):
        """DiscoveryExecutionConfig is immutable."""
        config_snapshot = json.dumps(valid_config_dict)
        config = parse_execution_config(config_snapshot)

        with pytest.raises(AttributeError):
            config.strategy_id = "modified"

    def test_prompt_config_is_frozen(self):
        """PromptConfig is immutable."""
        prompt = PromptConfig(
            id="test",
            version="1.0",
            hash="abc123",
            text="test prompt",
        )

        with pytest.raises(AttributeError):
            prompt.text = "modified"

    def test_llm_config_is_frozen(self):
        """LLMConfig is immutable."""
        llm = LLMConfig(
            provider="9router",
            combo="test-combo",
            temperature=0.5,
            max_candidates_per_window=5,
        )

        with pytest.raises(AttributeError):
            llm.temperature = 0.9

    def test_window_config_is_frozen(self):
        """WindowConfig is immutable."""
        window = WindowConfig(duration_seconds=300, overlap_seconds=60)

        with pytest.raises(AttributeError):
            window.duration_seconds = 600


class TestConstants:
    """Tests for module constants."""

    def test_max_window_attempts_value(self):
        """MAX_WINDOW_ATTEMPTS has expected value."""
        assert MAX_WINDOW_ATTEMPTS == 3
