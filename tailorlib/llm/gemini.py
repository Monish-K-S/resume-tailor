"""Google Gemini adapter (google-genai SDK)."""

from __future__ import annotations

import copy
from typing import Any, Sequence

from ..errors import ConfigError, LLMError
from .base import Message, parse_json_object


class GeminiClient:
    def __init__(self, api_key: str, model: str) -> None:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - dependency error
            raise ConfigError(
                "google-genai is not installed. Run: pip install google-genai"
            ) from exc

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        schema: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - dependency error
            raise ConfigError("google-genai is not installed") from exc

        contents = [
            {
                "role": "user" if message.role == "user" else "model",
                "parts": [{"text": message.content}],
            }
            for message in messages
        ]

        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    response_mime_type="application/json",
                    response_schema=_sanitize_schema(schema),
                ),
            )
        except Exception as exc:  # SDK raises provider-specific errors
            raise LLMError(f"Gemini request failed: {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            raise LLMError("Gemini returned an empty response")
        return parse_json_object(text)


def _sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini's responseSchema does not accept additionalProperties."""
    clean = copy.deepcopy(schema)
    clean.pop("additionalProperties", None)
    for value in clean.get("properties", {}).values():
        if isinstance(value, dict):
            value.pop("additionalProperties", None)
    return clean
