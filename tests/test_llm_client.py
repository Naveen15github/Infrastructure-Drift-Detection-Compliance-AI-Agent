"""
Tests for core/llm_client.py.

Covers key rotation logic on HTTP 429 and 402, all-keys-failed error,
successful completion, and code-fence stripping.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from core.llm_client import OpenRouterClient


def _make_response(status_code: int, content_text: str = "") -> MagicMock:
    """Build a mock requests.Response with given status and JSON body."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content_text}}]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestOpenRouterClientKeyRotation:
    """Test automatic API key rotation on rate/token limit responses."""

    def test_first_key_succeeds(self):
        """Returns response from key 1 when it gets HTTP 200."""
        client = OpenRouterClient(api_keys=["key1", "key2", "key3"])
        expected = '{"risk_score": 10}'

        with patch("core.llm_client.requests.post") as mock_post:
            mock_post.return_value = _make_response(200, expected)
            result = client.complete("sys", "user")

        assert result == expected
        assert mock_post.call_count == 1
        assert client.last_used_key_index == 0

    def test_rotates_on_429(self):
        """Skips key 1 on 429 and succeeds with key 2."""
        client = OpenRouterClient(api_keys=["key1", "key2", "key3"])
        expected = '{"risk_score": 5}'

        responses = [
            _make_response(429),
            _make_response(200, expected),
        ]
        with patch("core.llm_client.requests.post", side_effect=responses) as mock_post:
            result = client.complete("sys", "user")

        assert result == expected
        assert mock_post.call_count == 2
        assert client.last_used_key_index == 1

    def test_rotates_on_402(self):
        """Skips key 1 on 402 (credit limit) and succeeds with key 2."""
        client = OpenRouterClient(api_keys=["key1", "key2", "key3"])
        expected = '{"risk_score": 0}'

        responses = [
            _make_response(402),
            _make_response(200, expected),
        ]
        with patch("core.llm_client.requests.post", side_effect=responses):
            result = client.complete("sys", "user")

        assert result == expected

    def test_rotates_through_all_keys_before_failure(self):
        """Raises RuntimeError only after all three keys return 429."""
        client = OpenRouterClient(api_keys=["key1", "key2", "key3"])

        with patch(
            "core.llm_client.requests.post",
            return_value=_make_response(429),
        ) as mock_post:
            with pytest.raises(RuntimeError, match="All 3 OpenRouter API keys failed"):
                client.complete("sys", "user")

        assert mock_post.call_count == 3

    def test_raises_when_no_keys_configured(self):
        """Raises ValueError on instantiation when no API keys are provided."""
        with pytest.raises(ValueError, match="No OpenRouter API keys configured"):
            OpenRouterClient(api_keys=[])

    def test_strips_json_code_fence(self):
        """Removes ```json ... ``` fences from the model's response."""
        client = OpenRouterClient(api_keys=["key1"])
        raw = "```json\n{\"risk_score\": 10}\n```"

        with patch("core.llm_client.requests.post", return_value=_make_response(200, raw)):
            result = client.complete("sys", "user")

        assert "```" not in result
        parsed = json.loads(result)
        assert parsed["risk_score"] == 10

    def test_strips_plain_code_fence(self):
        """Removes plain ``` fences from the model's response."""
        client = OpenRouterClient(api_keys=["key1"])
        raw = "```\n{\"ok\": true}\n```"

        with patch("core.llm_client.requests.post", return_value=_make_response(200, raw)):
            result = client.complete("sys", "user")

        assert "```" not in result

    def test_key_used_is_sent_in_auth_header(self):
        """The Authorization header uses the active key."""
        client = OpenRouterClient(api_keys=["secret-key-1"])

        with patch("core.llm_client.requests.post", return_value=_make_response(200, "{}")) as mock_post:
            client.complete("sys", "user")

        call_kwargs = mock_post.call_args
        headers = call_kwargs[1]["headers"] if call_kwargs[1] else call_kwargs.kwargs.get("headers", {})
        assert "Bearer secret-key-1" in headers.get("Authorization", "")
