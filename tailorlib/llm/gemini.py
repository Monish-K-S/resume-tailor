"""Google Gemini adapter (google-genai SDK)."""

from __future__ import annotations

import copy
import time
from typing import Any, Sequence

from ..errors import ConfigError, LLMError
from .base import Message, parse_json_object

_RETRY_DELAYS = (1.0, 2.0, 4.0)

_TRANSIENT_MARKERS = (
    "resource_exhausted",
    "unavailable",
    "internal server error",
    "connection reset",
    "connection aborted",
    "connection refused",
    "timed out",
    "timeout",
    "econnreset",
    "econnrefused",
    "remoteprotocolerror",
)

_TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})


def _status_code(exc: Exception) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def _is_transient(exc: Exception) -> bool:
    """True for rate limits, server errors and dropped connections."""
    if _status_code(exc) in _TRANSIENT_CODES:
        return True
    text = str(exc).casefold()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


def _thinking_config(types: Any) -> Any:
    """Disable thinking so the output budget goes to the resume itself."""
    factory = getattr(types, "ThinkingConfig", None)
    if factory is None:
        return None
    try:
        return factory(thinking_budget=0)
    except TypeError:  # older SDK without thinking_budget
        return None


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

    def _call(self, types: Any, contents: Any, config: Any) -> Any:
        """One request, retried on transient provider/network failures."""
        last_exc: Exception | None = None
        for attempt in range(len(_RETRY_DELAYS) + 1):
            if attempt:
                time.sleep(_RETRY_DELAYS[attempt - 1])
            try:
                return self._client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except Exception as exc:  # SDK raises provider-specific errors
                last_exc = exc
                if not _is_transient(exc):
                    break
        raise LLMError(f"Gemini request failed: {last_exc}") from last_exc

    def ping(self) -> None:
        """Make one tiny live request to prove the key and model work."""
        try:
            from google.genai import types
        except ImportError as exc:  # pragma: no cover - dependency error
            raise ConfigError("google-genai is not installed") from exc

        kwargs: dict[str, Any] = {"temperature": 0.0, "max_output_tokens": 8}
        thinking = _thinking_config(types)
        if thinking is not None:
            kwargs["thinking_config"] = thinking

        self._call(
            types,
            "Reply with the single word: ok",
            types.GenerateContentConfig(**kwargs),
        )

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

        kwargs: dict[str, Any] = {
            "system_instruction": system,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
            "response_mime_type": "application/json",
            "response_schema": _sanitize_schema(schema),
        }
        thinking = _thinking_config(types)
        if thinking is not None:
            kwargs["thinking_config"] = thinking

        response = self._call(
            types, contents, types.GenerateContentConfig(**kwargs)
        )

        text = getattr(response, "text", None)
        if not text:
            reason = None
            try:
                reason = response.candidates[0].finish_reason
            except (AttributeError, IndexError, TypeError):
                pass
            raise LLMError(
                "Gemini returned an empty response"
                + (f" (finish reason: {reason})" if reason else "")
            )
        return parse_json_object(text)


def _sanitize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini's responseSchema does not accept additionalProperties."""
    clean = copy.deepcopy(schema)
    clean.pop("additionalProperties", None)
    for value in clean.get("properties", {}).values():
        if isinstance(value, dict):
            value.pop("additionalProperties", None)
    return clean
