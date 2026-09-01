"""Unit tests for NineRouterDiscoveryProvider.

Tests cover:
- HTTP success/error handling
- JSON validation and markdown stripping
- Segment ID validation
- Error types (unavailable, response error, validation error)
- DiscoveryProviderResult with resolved model info
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

from app.services.ninerouter_discovery_provider import (
    DiscoveryProviderResult,
    LLMResponseValidationError,
    NineRouterDiscoveryProvider,
    NineRouterError,
    NineRouterResponseError,
    NineRouterUnavailableError,
)
from app.services.transcript_window_builder import TranscriptWindow, WindowSegment


@pytest.fixture
def mock_window():
    """Create a mock transcript window with segments."""
    return TranscriptWindow(
        segments=[
            WindowSegment(
                id=1,
                start_seconds=0.0,
                end_seconds=10.0,
                text="First segment",
            ),
            WindowSegment(
                id=2,
                start_seconds=10.0,
                end_seconds=20.0,
                text="Second segment",
            ),
            WindowSegment(
                id=3,
                start_seconds=20.0,
                end_seconds=30.0,
                text="Third segment",
            ),
        ],
        start_seconds=0.0,
        end_seconds=30.0,
    )


@pytest.fixture
def valid_llm_response():
    """Valid LLM discovery response JSON."""
    return json.dumps({
        "clips": [
            {
                "start_segment_id": 1,
                "end_segment_id": 2,
                "title": "Test Clip",
                "hook": "Great opening",
                "summary": "A compelling clip",
            }
        ]
    })


class TestNineRouterDiscoveryProviderInit:
    """Tests for provider initialization."""

    def test_default_initialization(self):
        """Provider initializes with default settings."""
        provider = NineRouterDiscoveryProvider()
        assert provider.combo == "neoclips-discovery"
        assert provider.base_url == "http://localhost:20128"
        assert provider.max_candidates_per_window == 10
        assert provider.temperature == 0.3

    def test_custom_initialization(self):
        """Provider accepts custom parameters."""
        provider = NineRouterDiscoveryProvider(
            combo="custom-combo",
            base_url="http://custom:9999",
            api_key="test-key",
            max_candidates_per_window=5,
            temperature=0.5,
            timeout_seconds=60,
        )
        assert provider.combo == "custom-combo"
        assert provider.base_url == "http://custom:9999"
        assert provider.api_key == "test-key"
        assert provider.max_candidates_per_window == 5
        assert provider.temperature == 0.5
        assert provider.timeout_seconds == 60


class TestNineRouterDiscoveryProviderSuccess:
    """Tests for successful discovery."""

    @pytest.mark.asyncio
    async def test_discover_clips_success(self, mock_window, valid_llm_response):
        """Successful discovery returns validated response."""
        provider = NineRouterDiscoveryProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": valid_llm_response}}],
            "model": "gpt-4o-2024-08-06",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            result = await provider.discover_clips_with_model(mock_window)

            assert isinstance(result, DiscoveryProviderResult)
            assert result.requested_combo == "neoclips-discovery"
            assert result.resolved_model == "gpt-4o-2024-08-06"
            assert len(result.response.clips) == 1
            assert result.response.clips[0].start_segment_id == 1

    @pytest.mark.asyncio
    async def test_discover_clips_backward_compat(self, mock_window, valid_llm_response):
        """discover_clips returns tuple for backward compatibility."""
        provider = NineRouterDiscoveryProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": valid_llm_response}}],
            "model": "claude-3-sonnet",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            response, raw_content = await provider.discover_clips(mock_window)

            assert len(response.clips) == 1
            assert raw_content == valid_llm_response


class TestNineRouterDiscoveryProviderErrors:
    """Tests for error handling."""

    @pytest.mark.asyncio
    async def test_connection_error_raises_unavailable(self, mock_window):
        """Connection error raises NineRouterUnavailableError."""
        provider = NineRouterDiscoveryProvider()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection failed"))
            mock_client_class.return_value = mock_client

            with pytest.raises(NineRouterUnavailableError) as exc_info:
                await provider.discover_clips(mock_window)

            assert "unreachable" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_timeout_raises_unavailable(self, mock_window):
        """Timeout raises NineRouterUnavailableError."""
        provider = NineRouterDiscoveryProvider()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("Timeout"))
            mock_client_class.return_value = mock_client

            with pytest.raises(NineRouterUnavailableError) as exc_info:
                await provider.discover_clips(mock_window)

            assert "timeout" in str(exc_info.value).lower()

    @pytest.mark.asyncio
    async def test_http_error_raises_response_error(self, mock_window):
        """HTTP error raises NineRouterResponseError."""
        provider = NineRouterDiscoveryProvider()

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        http_error = httpx.HTTPStatusError("Server error", request=MagicMock(), response=mock_response)

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(side_effect=http_error)
            mock_client_class.return_value = mock_client

            with pytest.raises(NineRouterResponseError) as exc_info:
                await provider.discover_clips(mock_window)

            assert "500" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_empty_response_raises_response_error(self, mock_window):
        """Empty response raises NineRouterResponseError."""
        provider = NineRouterDiscoveryProvider()

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": ""}}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_class.return_value = mock_client

            with pytest.raises(NineRouterResponseError) as exc_info:
                await provider.discover_clips(mock_window)

            assert "empty" in str(exc_info.value).lower()


class TestNineRouterDiscoveryProviderValidation:
    """Tests for response validation."""

    def test_validate_valid_json(self, mock_window, valid_llm_response):
        """Valid JSON passes validation."""
        provider = NineRouterDiscoveryProvider()
        result = provider._validate_response(valid_llm_response, mock_window)
        assert len(result.clips) == 1

    def test_validate_invalid_json_raises_error(self, mock_window):
        """Invalid JSON raises LLMResponseValidationError."""
        provider = NineRouterDiscoveryProvider()
        with pytest.raises(LLMResponseValidationError) as exc_info:
            provider._validate_response("not json", mock_window)
        assert "Invalid JSON" in str(exc_info.value)
        assert exc_info.value.raw_response == "not json"

    def test_validate_missing_clips_raises_error(self, mock_window):
        """Missing clips array raises LLMResponseValidationError."""
        provider = NineRouterDiscoveryProvider()
        with pytest.raises(LLMResponseValidationError):
            provider._validate_response('{"no_clips": []}', mock_window)

    def test_validate_invalid_segment_id_raises_error(self, mock_window):
        """Invalid segment ID raises LLMResponseValidationError."""
        provider = NineRouterDiscoveryProvider()
        invalid_response = json.dumps({
            "clips": [
                {
                    "start_segment_id": 999,  # Not in window
                    "end_segment_id": 2,
                    "title": "Test",
                    "hook": "Hook",
                    "summary": "Summary",
                }
            ]
        })
        with pytest.raises(LLMResponseValidationError) as exc_info:
            provider._validate_response(invalid_response, mock_window)
        assert "start_segment_id" in str(exc_info.value)
        assert "999" in str(exc_info.value)

    def test_validate_strips_markdown_code_blocks(self, mock_window, valid_llm_response):
        """Markdown code blocks are stripped before parsing."""
        provider = NineRouterDiscoveryProvider()
        markdown_response = f"```json\n{valid_llm_response}\n```"
        result = provider._validate_response(markdown_response, mock_window)
        assert len(result.clips) == 1

    def test_validate_without_window_skips_segment_validation(self):
        """Validation without window skips segment ID check."""
        provider = NineRouterDiscoveryProvider()
        response_with_invalid_segment = json.dumps({
            "clips": [
                {
                    "start_segment_id": 999,
                    "end_segment_id": 1000,
                    "title": "Test",
                    "hook": "Hook",
                    "summary": "Summary",
                }
            ]
        })
        # Should not raise - window is None
        result = provider._validate_response(response_with_invalid_segment, None)
        assert len(result.clips) == 1


class TestDiscoveryProviderResult:
    """Tests for DiscoveryProviderResult dataclass."""

    def test_result_creation(self, valid_llm_response):
        """Result stores all fields correctly."""
        from app.schemas.discovery import LLMDiscoveryResponse

        parsed = LLMDiscoveryResponse(**json.loads(valid_llm_response))
        result = DiscoveryProviderResult(
            response=parsed,
            raw_content=valid_llm_response,
            requested_combo="test-combo",
            resolved_model="gpt-4o",
        )

        assert result.response == parsed
        assert result.raw_content == valid_llm_response
        assert result.requested_combo == "test-combo"
        assert result.resolved_model == "gpt-4o"

    def test_result_without_resolved_model(self, valid_llm_response):
        """Result can have None resolved_model."""
        from app.schemas.discovery import LLMDiscoveryResponse

        parsed = LLMDiscoveryResponse(**json.loads(valid_llm_response))
        result = DiscoveryProviderResult(
            response=parsed,
            raw_content=valid_llm_response,
            requested_combo="test-combo",
        )

        assert result.resolved_model is None


class TestErrorHierarchy:
    """Tests for error class hierarchy."""

    def test_unavailable_is_ninerouter_error(self):
        """NineRouterUnavailableError is a NineRouterError."""
        assert issubclass(NineRouterUnavailableError, NineRouterError)

    def test_response_is_ninerouter_error(self):
        """NineRouterResponseError is a NineRouterError."""
        assert issubclass(NineRouterResponseError, NineRouterError)

    def test_validation_is_ninerouter_error(self):
        """LLMResponseValidationError is a NineRouterError."""
        assert issubclass(LLMResponseValidationError, NineRouterError)


class TestPromptBuilding:
    """Tests for prompt building."""

    def test_system_prompt_uses_canonical(self):
        """System prompt uses canonical prompt from prompts module."""
        provider = NineRouterDiscoveryProvider()
        prompt = provider._build_system_prompt()
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_user_prompt_includes_segments(self, mock_window):
        """User prompt includes segment information."""
        provider = NineRouterDiscoveryProvider()
        prompt = provider._build_user_prompt(mock_window)

        assert "[1]" in prompt
        assert "[2]" in prompt
        assert "First segment" in prompt
        assert "Second segment" in prompt
        assert "0.0s" in prompt
        assert "30.0s" in prompt
