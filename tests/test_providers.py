from __future__ import annotations

import pytest

from tailorlib.errors import ConfigError, LLMError
from tailorlib.llm import build_client, parse_json_object


def clear_env(monkeypatch):
    for name in (
        "RESUME_TAILOR_PROVIDER",
        "RESUME_TAILOR_MODEL",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_gemini_is_the_default_provider(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "dummy")

    client = build_client()

    assert type(client).__name__ == "GeminiClient"
    assert client.model == "gemini-2.5-flash"


def test_gemini_without_key_is_a_config_error(monkeypatch):
    clear_env(monkeypatch)
    with pytest.raises(ConfigError, match="GEMINI_API_KEY"):
        build_client()


def test_openai_has_a_default_model(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    client = build_client("openai")

    assert type(client).__name__ == "OpenAICompatClient"
    assert client.model == "gpt-4o-mini"


def test_openrouter_requires_an_explicit_model(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    with pytest.raises(ConfigError, match="RESUME_TAILOR_MODEL"):
        build_client("openrouter")


def test_openrouter_uses_its_base_url(monkeypatch):
    clear_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "dummy")

    client = build_client("openrouter", "meta/llama")

    assert client.model == "meta/llama"
    assert str(client._client.base_url).startswith("https://openrouter.ai/api/v1")


def test_ollama_needs_no_real_key(monkeypatch):
    clear_env(monkeypatch)

    client = build_client("ollama", "llama3")

    assert str(client._client.base_url).startswith("http://localhost:11434/v1")


def test_unknown_provider_is_a_config_error(monkeypatch):
    clear_env(monkeypatch)
    with pytest.raises(ConfigError, match="unknown provider"):
        build_client("magic")


def test_parse_json_object_handles_fences_and_prose():
    assert parse_json_object('```json\n{"body": "x"}\n```') == {"body": "x"}
    assert parse_json_object('Sure! Here it is: {"body": "y"} Hope that helps.') == {
        "body": "y"
    }


def test_parse_json_object_rejects_garbage():
    with pytest.raises(LLMError):
        parse_json_object("no json here")
    with pytest.raises(LLMError):
        parse_json_object('{"body": }')
    with pytest.raises(LLMError):
        parse_json_object("[1, 2]")
