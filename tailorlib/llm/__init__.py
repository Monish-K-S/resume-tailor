"""Provider factory. Configuration is environment-only."""

from __future__ import annotations

import os

from ..errors import ConfigError
from .base import LLMClient, Message, parse_json_object

__all__ = ["LLMClient", "Message", "build_client", "parse_json_object"]

DEFAULT_PROVIDER = "tokenharbor"

DEFAULT_MODELS = {
    "tokenharbor": "deepseek-v4.1-flash:free",
    "gemini": "gemini-3.8-flash",
    "openai": "gpt-4o-mini",
}

OPENAI_ALIASES = {
    "tokenharbor",
    "openai",
    "openai-compatible",
    "openrouter",
    "groq",
    "ollama",
    "local",
}

DEFAULT_BASE_URLS = {
    "tokenharbor": "https://tokenharbor.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
    "local": "http://localhost:11434/v1",
}

# Provider -> (preferred key variable, fallback key variable)
KEY_VARIABLES = {
    "tokenharbor": ("TOKENHARBOR_API_KEY", "OPENAI_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "openai-compatible": ("OPENAI_API_KEY",),
    "openrouter": ("OPENAI_API_KEY",),
    "groq": ("OPENAI_API_KEY",),
    "ollama": ("OPENAI_API_KEY",),
    "local": ("OPENAI_API_KEY",),
}


def _api_key(name: str) -> str:
    variables = KEY_VARIABLES.get(name, ("OPENAI_API_KEY",))
    for variable in variables:
        value = os.getenv(variable)
        if value:
            return value
    if name in {"ollama", "local"}:
        return "ollama"
    raise ConfigError(" or ".join(variables) + " is not set")


def build_client(provider: str | None = None, model: str | None = None) -> LLMClient:
    name = (
        provider or os.getenv("RESUME_TAILOR_PROVIDER") or DEFAULT_PROVIDER
    ).strip().lower()
    model = (model or os.getenv("RESUME_TAILOR_MODEL") or "").strip() or None

    if name == "gemini":
        from .gemini import GeminiClient

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ConfigError("GEMINI_API_KEY (or GOOGLE_API_KEY) is not set")
        return GeminiClient(api_key, model or DEFAULT_MODELS["gemini"])

    if name in OPENAI_ALIASES:
        from .openai_compat import OpenAICompatClient

        api_key = _api_key(name)

        if not model:
            model = DEFAULT_MODELS.get(name)
            if not model:
                raise ConfigError(
                    f"RESUME_TAILOR_MODEL is required for provider '{name}'"
                )

        base_url = os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URLS.get(name)
        return OpenAICompatClient(api_key, model, base_url)

    raise ConfigError(
        f"unknown provider '{name}'; use 'tokenharbor', 'gemini', or another "
        "OpenAI-compatible provider"
    )
