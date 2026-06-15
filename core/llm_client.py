"""
OpenRouter API client with automatic key rotation on rate-limit and token-limit errors.

Provides a simple complete() interface used by the agent's risk analysis node.
"""

import json
import re
from typing import List

import requests

from config.settings import settings


class OpenRouterClient:
    """HTTP client for the OpenRouter chat completions API.

    Automatically rotates through up to three API keys when HTTP 429 (rate limit)
    or HTTP 402 (token/credit limit) responses are received.
    """

    def __init__(self, api_keys: List[str] | None = None) -> None:
        """Initialise with a list of API keys.

        Args:
            api_keys: Optional override list of keys. Defaults to settings.openrouter_api_keys.
        """
        self._keys: List[str] = api_keys or settings.openrouter_api_keys
        if not self._keys:
            raise ValueError(
                "No OpenRouter API keys configured. "
                "Set OPENROUTER_API_KEY_1, _2, or _3 in your environment."
            )
        self._last_used_key_index: int = -1

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Send a chat completion request, rotating keys on 429/402.

        Args:
            system_prompt: Instruction context for the model.
            user_prompt: The user turn content.

        Returns:
            Raw text content from the first assistant message.

        Raises:
            RuntimeError: When all configured API keys have been exhausted.
        """
        last_error: Exception | None = None

        for index, key in enumerate(self._keys):
            self._last_used_key_index = index
            try:
                response = self._post(key, system_prompt, user_prompt)
                status = response.status_code

                if status in (429, 402):
                    last_error = RuntimeError(
                        f"Key index {index} returned HTTP {status}. Trying next key."
                    )
                    continue

                response.raise_for_status()
                raw_text = self._extract_text(response.json())
                return self._strip_code_fences(raw_text)

            except requests.RequestException as exc:
                last_error = exc
                continue

        raise RuntimeError(
            f"All {len(self._keys)} OpenRouter API keys failed. "
            f"Last error: {last_error}"
        )

    @property
    def last_used_key_index(self) -> int:
        """Return the zero-based index of the last key that was attempted."""
        return self._last_used_key_index

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _post(self, api_key: str, system_prompt: str, user_prompt: str) -> requests.Response:
        """Execute the HTTP POST to the OpenRouter completions endpoint.

        Args:
            api_key: Bearer token for authentication.
            system_prompt: System role message content.
            user_prompt: User role message content.

        Returns:
            Raw requests.Response object.
        """
        payload = {
            "model": settings.openrouter_model,
            "max_tokens": 1024,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/self-healing-terraform",
            "X-Title": "Self-Healing Terraform Agent",
        }
        return requests.post(
            settings.openrouter_base_url,
            headers=headers,
            data=json.dumps(payload),
            timeout=120,
        )

    @staticmethod
    def _extract_text(response_json: dict) -> str:
        """Pull the assistant message text out of the API response.

        Args:
            response_json: Parsed JSON body from the API.

        Returns:
            Text content of the first choice.

        Raises:
            ValueError: If the response shape is unexpected.
        """
        try:
            return response_json["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise ValueError(
                f"Unexpected OpenRouter response shape: {response_json}"
            ) from exc

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Remove markdown code fences that the model may wrap around JSON.

        Args:
            text: Raw model output.

        Returns:
            Cleaned string with fences removed.
        """
        # Remove ```json ... ``` or ``` ... ```
        cleaned = re.sub(r"```(?:json)?\s*", "", text)
        cleaned = cleaned.replace("```", "")
        return cleaned.strip()
