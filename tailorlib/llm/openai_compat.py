"""OpenAI-compatible adapter: OpenAI, OpenRouter, Groq, Ollama, local servers."""

from __future__ import annotations

from typing import Any, Sequence

from ..errors import ConfigError, LLMError
from .base import Message, configured_timeout, parse_json_object


class OpenAICompatClient:
    def __init__(self, api_key: str, model: str, base_url: str | None = None) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover - dependency error
            raise ConfigError(
                "openai is not installed. Run: pip install openai"
            ) from exc

        timeout = configured_timeout()
        self._client = (
            OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                max_retries=1,
            )
            if base_url
            else OpenAI(api_key=api_key, timeout=timeout, max_retries=1)
        )
        self.model = model
        # Only OpenAI itself is guaranteed to support strict json_schema.
        self._strict_schema = base_url is None or "api.openai.com" in base_url

    def ping(self) -> None:
        """Make one tiny live request to prove the key and model work."""
        try:
            self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Reply with: ok"}],
                temperature=0.0,
                max_tokens=5,
            )
        except Exception as exc:  # SDK raises provider-specific errors
            raise LLMError(f"API request failed: {exc}") from exc

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        schema: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        payload = [
            {"role": "system", "content": system},
            *[{"role": message.role, "content": message.content} for message in messages],
        ]

        request: dict[str, Any] = {
            "model": self.model,
            "messages": payload,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self._strict_schema:
            request["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "resume_tailor",
                    "strict": True,
                    "schema": schema,
                },
            }
        else:
            request["response_format"] = {"type": "json_object"}

        try:
            response = self._client.chat.completions.create(**request)
        except Exception as exc:  # SDK raises provider-specific errors
            raise LLMError(f"API request failed: {exc}") from exc

        content = response.choices[0].message.content if response.choices else None
        if not content:
            raise LLMError("provider returned an empty response")
        return parse_json_object(content)
