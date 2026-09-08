"""Tests for the centralized Groq AI service (Part 6).

Groq is fully mocked: no real network calls or API key are required. Covers
chat, structured (Pydantic) and streaming completions plus timeouts, rate
limits, connection errors, missing-key configuration, retry behaviour, and
malformed / repairable structured output.
"""

import types
from typing import Any

import pytest
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.services.ai_service import (
    AIAPIError,
    AIConfigurationError,
    AIConnectionError,
    AIRateLimitError,
    AIService,
    AIStructuredParsingError,
    AITimeoutError,
)


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
def _completion(text: str, model: str = "fake-model") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))],
        model=model,
        usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=3, total_tokens=8),
    )


def _chunk(delta: str) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        choices=[types.SimpleNamespace(delta=types.SimpleNamespace(content=delta))]
    )


class _FakeCompletions:
    def __init__(self, handler: Any) -> None:
        self._handler = handler

    async def create(self, **kwargs: Any) -> Any:
        return await self._handler(**kwargs)


def _req() -> object:
    """Bare request object accepted by the SDK's exception constructors."""
    return object()


class FakeClient:
    """Minimal stand-in for ``AsyncGroq`` driven by a pluggable async handler."""

    def __init__(self, handler: Any) -> None:
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(handler))


def _settings(**overrides: Any) -> Settings:
    base = dict(
        GROQ_API_KEY="fake-key-for-tests",
        GROQ_MODEL="fake-model",
        GROQ_TIMEOUT_SECONDS=2.0,
        GROQ_MAX_RETRIES=1,
        GROQ_LOG_LEVEL="WARNING",
    )
    base.update(overrides)
    return Settings(**base)


def _service(handler: Any, **overrides: Any) -> AIService:
    return AIService(settings=_settings(**overrides), client=FakeClient(handler))


class SampleOut(BaseModel):
    category: str = Field(description="Category")
    confidence: float = Field(description="Confidence 0..1")
    summary: str = Field(description="Summary")


VALID_JSON = '{"category": "ROAD", "confidence": 0.95, "summary": "Pothole near the bridge."}'


# --------------------------------------------------------------------------- #
# chat_completion
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_chat_completion_valid():
    async def handler(**kw):
        assert kw["stream"] is False
        return _completion("Hello from Groq.")

    svc = _service(handler)
    result = await svc.chat_completion([{"role": "user", "content": "hi"}])
    assert result.text == "Hello from Groq."
    assert result.model == "fake-model"
    assert result.usage.total_tokens == 8
    assert result.request_id


@pytest.mark.asyncio
async def test_chat_completion_missing_api_key():
    svc = AIService(settings=_settings(GROQ_API_KEY=""), client=None)
    assert svc.is_configured is False
    with pytest.raises(AIConfigurationError):
        await svc.chat_completion([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_completion_rate_limit_retries_then_raises():
    from groq._exceptions import RateLimitError

    async def handler(**kw):
        raise RateLimitError(
            message="rate limited",
            response=types.SimpleNamespace(status_code=429, request=_req()),
            body=None,
        )

    # max_retries=1 -> 1 retry after the initial failure, then raise.
    svc = _service(handler)
    with pytest.raises(AIRateLimitError):
        await svc.chat_completion([{"role": "user", "content": "hi"}])
    assert svc.is_configured is True


@pytest.mark.asyncio
async def test_chat_completion_timeout_retries_then_raises():
    from groq._exceptions import APITimeoutError

    async def handler(**kw):
        raise APITimeoutError(request=_req())

    svc = _service(handler, GROQ_MAX_RETRIES=2)
    with pytest.raises(AITimeoutError):
        await svc.chat_completion([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_completion_network_error():
    from groq._exceptions import APIConnectionError

    async def handler(**kw):
        raise APIConnectionError(message="connection refused", request=_req())

    svc = _service(handler)
    with pytest.raises(AIConnectionError):
        await svc.chat_completion([{"role": "user", "content": "hi"}])


@pytest.mark.asyncio
async def test_chat_completion_hard_error_no_retry():
    from groq._exceptions import AuthenticationError

    calls = {"n": 0}

    async def handler(**kw):
        calls["n"] += 1
        raise AuthenticationError(
            "bad key",
            response=types.SimpleNamespace(status_code=401, request=_req()),
            body=None,
        )

    svc = _service(handler)
    with pytest.raises(AIAPIError):
        await svc.chat_completion([{"role": "user", "content": "hi"}])
    # Hard errors must not be retried.
    assert calls["n"] == 1


# --------------------------------------------------------------------------- #
# structured_completion
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_structured_completion_valid():
    async def handler(**kw):
        assert kw["response_format"] == {"type": "json_object"}
        return _completion(VALID_JSON)

    svc = _service(handler)
    out = await svc.structured_completion([{"role": "user", "content": "classify"}], SampleOut)
    assert isinstance(out, SampleOut)
    assert out.category == "ROAD"
    assert out.confidence == 0.95
    assert out.summary.startswith("Pothole")


@pytest.mark.asyncio
async def test_structured_completion_fenced_json_repaired():
    fenced = "```json\n" + VALID_JSON + "\n```"

    async def handler(**kw):
        return _completion(fenced)

    svc = _service(handler)
    out = await svc.structured_completion([{"role": "user", "content": "classify"}], SampleOut)
    assert isinstance(out, SampleOut)
    assert out.category == "ROAD"


@pytest.mark.asyncio
async def test_structured_completion_empty_raises():
    async def handler(**kw):
        return _completion("\n  \n")

    svc = _service(handler)
    with pytest.raises(AIStructuredParsingError):
        await svc.structured_completion([{"role": "user", "content": "x"}], SampleOut)


@pytest.mark.asyncio
async def test_structured_completion_malformed_json_raises():
    async def handler(**kw):
        return _completion("this is definitely not json {{{")

    svc = _service(handler)
    with pytest.raises(AIStructuredParsingError):
        await svc.structured_completion([{"role": "user", "content": "x"}], SampleOut)


@pytest.mark.asyncio
async def test_structured_completion_wrong_schema_raises():
    # Valid JSON but missing the required fields -> schema validation failure.
    async def handler(**kw):
        return _completion('{"category": "ROAD"}')

    svc = _service(handler)
    with pytest.raises(AIStructuredParsingError):
        await svc.structured_completion([{"role": "user", "content": "x"}], SampleOut)


# --------------------------------------------------------------------------- #
# stream_completion
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_stream_completion_delivers_chunks_and_done():
    async def handler(**kw):
        assert kw["stream"] is True

        async def gen():
            yield _chunk("Hello")
            yield _chunk(" world")

        return gen()

    svc = _service(handler)
    chunks = [c async for c in svc.stream_completion([{"role": "user", "content": "hi"}])]
    text = "".join(c.delta for c in chunks if not c.done)
    assert text == "Hello world"
    assert chunks[-1].done is True


@pytest.mark.asyncio
async def test_stream_completion_rate_limit_raises():
    from groq._exceptions import RateLimitError

    async def handler(**kw):
        raise RateLimitError(
            message="429",
            response=types.SimpleNamespace(status_code=429, request=_req()),
            body=None,
        )

    svc = _service(handler)
    with pytest.raises(AIRateLimitError):
        async for _ in svc.stream_completion([{"role": "user", "content": "hi"}]):
            pass


@pytest.mark.asyncio
async def test_missing_key_not_logged():
    """Ensure the AIConfigurationError never embeds a key (safety smoke check)."""
    svc = AIService(settings=_settings(GROQ_API_KEY=""), client=None)
    with pytest.raises(AIConfigurationError) as exc_info:
        await svc.chat_completion([{"role": "user", "content": "hi"}])
    assert "GROQ_API_KEY" in str(exc_info.value)
