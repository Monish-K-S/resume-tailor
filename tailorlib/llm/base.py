"""Provider-neutral request/response types shared by the adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from ..errors import LLMError


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
