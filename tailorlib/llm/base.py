"""Provider-neutral request/response types shared by the adapters."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..errors import LLMError

DEFAULT_TIMEOUT_S = 30.0


def configured_timeout(default: float = DEFAULT_TIMEOUT_S) -> float:
    """Per-request timeout in seconds (RESUME_TAILOR_TIMEOUT overrides)."""
    raw = os.getenv("RESUME_TAILOR_TIMEOUT")
    try:
        seconds = float(raw) if raw else default
    except ValueError:
        seconds = default
    return min(max(seconds, 5.0), 300.0)


@dataclass(frozen=True)
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLMClient(Protocol):
    def ping(self) -> None:
        """Make one tiny live request to prove the key and model work."""

    def complete(
        self,
        *,
        system: str,
        messages: Sequence[Message],
        schema: dict[str, Any],
        temperature: float = 0.2,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Return the structured JSON object the model produced."""


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse JSON that may be wrapped in prose or markdown fences."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1] if "\n" in stripped else ""
        if stripped.endswith("```"):
            stripped = stripped[:-3]
        stripped = stripped.strip()

    start = stripped.find("{")
    if start == -1:
        raise LLMError(f"model response did not contain a JSON object: {text[:200]!r}")

    try:
        value, _ = json.JSONDecoder().raw_decode(stripped[start:])
    except json.JSONDecodeError as exc:
        raise LLMError(f"model response was not valid JSON: {exc}") from exc

    if not isinstance(value, dict):
        raise LLMError("model response JSON was not an object")
    return value
