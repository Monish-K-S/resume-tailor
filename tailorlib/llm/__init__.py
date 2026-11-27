"""Provider factory. Configuration is environment-only."""

from __future__ import annotations

import os

from ..errors import ConfigError
from .base import LLMClient, Message, parse_json_object

__all__ = ["LLMClient", "Message", "build_client", "parse_json_object"]

DEFAULT_MODELS = {
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
}

OPENAI_ALIASES = {
    "openai",
    "openai-compatible",
    "openrouter",
    "groq",
    "ollama",
    "local",
}

DEFAULT_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
    "local": "http://localhost:11434/v1",
}


def build_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    name = (provider or os.getenv("RESUME_TAILOR_PROVIDER") or "gemini").strip().lower()
    model = (model or os.getenv("RESUME_TAILOR_MODEL") or "").strip() or None

    if name == "gemini":
        from .gemini import GeminiClient

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ConfigError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set")
        return GeminiClient(api_key, model or DEFAULT_MODELS["gemini"])

    if name in OPENAI_ALIASES:
        from .openai_compat import OpenAICompatClient

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key and name in {"ollama", "local"}:
            api_key = "ollama"
        if not api_key:
            raise ConfigError("OPENAI_API_KEY is not set")

        if not model:
            if name == "openai":
                model = DEFAULT_MODELS["openai"]
            else:
                raise ConfigError(
                    f"RESUME_TAILOR_MODEL is required for provider '{name}'"
                )

        base_url = os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URLS.get(name)
        return OpenAICompatClient(api_key, model, base_url)

    raise ConfigError(
        f"unknown provider '{name}'; use 'gemini' or an OpenAI-compatible provider"
    )
