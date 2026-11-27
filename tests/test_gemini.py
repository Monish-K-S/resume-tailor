from __future__ import annotations

import pytest

from tailorlib.errors import LLMError
from tailorlib.llm.base import Message
from tailorlib.llm.gemini import (
    GeminiClient,
    _is_transient,
    _sanitize_schema,
    _thinking_config,
)

SCHEMA = {
    "type": "object",
    "properties": {"body": {"type": "string"}},
    "required": ["body"],
    "additionalProperties": False,
}


def test_sanitize_schema_drops_additional_properties():
    clean = _sanitize_schema(SCHEMA)
    assert "additionalProperties" not in clean
    assert clean["properties"]["body"] == {"type": "string"}


def test_is_transient_matches_server_and_network_errors():
    assert _is_transient(Exception("503 UNAVAILABLE"))
    assert _is_transient(Exception("429 RESOURCE_EXHAUSTED"))
    assert _is_transient(Exception("[Errno 54] Connection reset by peer"))
    assert not _is_transient(Exception("404 NOT_FOUND"))


def test_is_transient_uses_the_status_code_attribute():
    class ApiError(Exception):
        def __init__(self, code: int, message: str) -> None:
            super().__init__(message)
            self.code = code

    assert _is_transient(ApiError(503, "server busy"))
    assert _is_transient(ApiError(429, "slow down"))
    assert not _is_transient(ApiError(404, "not found"))


def test_thinking_is_disabled_when_supported():
    from google.genai import types

    config = _thinking_config(types)
    assert config is not None
    assert config.thinking_budget == 0


def test_thinking_config_tolerates_old_sdks():
    class OldTypes:
        pass

    assert _thinking_config(OldTypes()) is None


class FakeResponse:
    text = '{"body": "hello"}'
    candidates: list = []


class FakeModels:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests: list[dict] = []

    def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def make_client(outcomes) -> tuple[GeminiClient, FakeModels]:
    models = FakeModels(outcomes)
    client = object.__new__(GeminiClient)
    client._client = type("C", (), {"models": models})()
    client.model = "gemini-3.8-flash"
    return client, models


def test_complete_disables_thinking_and_parses_json(monkeypatch):
    client, models = make_client([FakeResponse()])

    result = client.complete(
        system="system",
        messages=[Message("user", "hi")],
        schema=SCHEMA,
    )

    assert result == {"body": "hello"}
    config = models.requests[0]["config"]
    assert config.thinking_config.thinking_budget == 0
    assert "additionalProperties" not in config.response_schema


def test_complete_retries_transient_failures(monkeypatch):
    monkeypatch.setattr("tailorlib.llm.gemini.time.sleep", lambda _: None)
    client, models = make_client(
        [Exception("503 UNAVAILABLE"), FakeResponse()]
    )

    result = client.complete(
        system="system",
        messages=[Message("user", "hi")],
        schema=SCHEMA,
    )

    assert result == {"body": "hello"}
    assert len(models.requests) == 2


def test_complete_does_not_retry_permanent_failures(monkeypatch):
    monkeypatch.setattr("tailorlib.llm.gemini.time.sleep", lambda _: None)
    client, models = make_client([Exception("404 NOT_FOUND")])

    with pytest.raises(LLMError, match="404"):
        client.complete(
            system="system",
            messages=[Message("user", "hi")],
            schema=SCHEMA,
        )

    assert len(models.requests) == 1


def test_complete_reports_empty_response():
    class Empty:
        text = None
        candidates: list = []

    client, _ = make_client([Empty()])

    with pytest.raises(LLMError, match="empty response"):
        client.complete(
            system="system",
            messages=[Message("user", "hi")],
            schema=SCHEMA,
        )


def test_ping_is_a_live_request(monkeypatch):
    client, models = make_client([FakeResponse()])

    client.ping()

    assert models.requests[0]["contents"] == "Reply with the single word: ok"
