"""Central Groq AI integration layer (Part 6).

Provides chat, structured (Pydantic-validated) and streaming completions with
retries, timeouts, rate-limit handling, connection-error handling, structured
logging, per-call request IDs and model configuration.

The provider key is read only from environment configuration (``Settings``);
it is never logged and never exposed to the browser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, TypeVar

from groq import AsyncGroq
from groq._exceptions import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    RateLimitError,
)
from groq.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)


class AIError(Exception):
    """Base class for controlled AI-service failures."""


class AIConfigurationError(AIError):
    """Raised when no Groq API key is configured."""


class AITimeoutError(AIError):
    """Raised when a Groq request exceeds the configured timeout."""


class AIRateLimitError(AIError):
    """Raised when Groq returns a rate-limit (429) response.

    ``retry_after_seconds`` carries Groq's ``Retry-After`` response header when
    the provider supplied one, so callers can surface a precise wait hint to
    the user instead of guessing.
    """

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class AIConnectionError(AIError):
    """Raised when Groq cannot be reached (network / DNS / transport)."""


class AIAPIError(AIError):
    """Raised for any other provider error (auth, 5xx, etc.).

    ``code`` carries the provider's machine-readable error code when one is
    available (e.g. Groq's ``json_validate_failed``), so callers can decide
    whether a generation failure is recoverable.
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class AIStructuredParsingError(AIError):
    """Raised when a structured response cannot be parsed or validated.

    Callers should treat this as a controlled human-review failure.
    """


@dataclass
class AIUsage:
    """Token usage reported by the provider (best effort)."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class AICompletionResult:
    """Result of a non-streaming chat / structured completion."""

    text: str
    request_id: str
    model: str
    usage: AIUsage | None = None


@dataclass
class AIStreamChunk:
    """A single streaming chunk pushed to the caller."""

    delta: str
    request_id: str
    model: str
    done: bool = False


def _build_client(settings: Settings) -> AsyncGroq | None:
    """Build the async Groq client, or ``None`` when no key is configured.

    The client is created lazily so unit tests can inject fakes and so a
    missing key (a configuration problem) is handled explicitly rather than
    raising at import time.
    """
    if not settings.GROQ_API_KEY:
        return None
    return AsyncGroq(
        api_key=settings.GROQ_API_KEY,
        max_retries=settings.GROQ_MAX_RETRIES,
        timeout=settings.GROQ_TIMEOUT_SECONDS,
        default_headers={"User-Agent": f"{settings.PROJECT_NAME}/{settings.VERSION}"},
    )


class AIService:
    """Centralized Groq integration with retries, timeouts and safe parsing."""

    def __init__(
        self,
        settings: Settings | None = None,
        client: AsyncGroq | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._model = self._settings.GROQ_MODEL
        self._timeout = self._settings.GROQ_TIMEOUT_SECONDS
        self._max_retries = self._settings.GROQ_MAX_RETRIES
        self._log_level = self._settings.GROQ_LOG_LEVEL.upper()
        self._client = client if client is not None else _build_client(self._settings)

    # ------------------------------------------------------------------ #
    # internal helpers
    # ------------------------------------------------------------------ #
    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def _require_client(self) -> AsyncGroq:
        if self._client is None:
            raise AIConfigurationError(
                "Groq is not configured. Set GROQ_API_KEY in the environment."
            )
        return self._client

    @staticmethod
    def _new_request_id() -> str:
        return str(uuid.uuid4())

    def _log(self, level: str, message: str, **kwargs: Any) -> None:
        # Emit at the module logger's native level; the configured service level
        # is advisory only so we never drop error/diagnostic context.
        record = {"ai.service": "groq", **kwargs}
        getattr(logger, level, logger.info)("%s %s", message, record)

    def _translate_error(
        self,
        exc: APIError,
        request_id: str,
    ) -> AIError:
        if isinstance(exc, APITimeoutError):
            return AITimeoutError(
                f"Groq request timed out after {self._timeout:.1f}s (request {request_id})."
            )
        if isinstance(exc, RateLimitError):
            return AIRateLimitError(
                f"Groq rate limit reached (request {request_id}); retry later.",
                retry_after_seconds=_retry_after_from(exc),
            )
        if isinstance(exc, APIConnectionError):
            return AIConnectionError(f"Unable to reach the Groq API (request {request_id}).")
        detail = getattr(exc, "body", None) or str(exc)
        code: str | None = None
        if isinstance(detail, dict):
            error = detail.get("error") or {}
            if isinstance(error, dict):
                code = error.get("code")
        return AIAPIError(f"Groq API error (request {request_id}): {detail!r}", code=code)

    async def _run_with_retry(
        self,
        request_id: str,
        fn: Any,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute the async ``fn``, retrying transient failures deliberately.

        Rate-limit (429), timeout and connection errors are retried with a tiny
        backoff; hard provider errors and auth failures fail fast.
        """
        attempt = 0
        while True:
            try:
                return await fn(*args, **kwargs)
            except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
                attempt += 1
                last_error = self._translate_error(exc, request_id)
                if attempt > self._max_retries:
                    self._log(
                        "error",
                        "Groq call failed after retries",
                        request_id=request_id,
                        error=type(last_error).__name__,
                        attempts=attempt,
                    )
                    raise last_error from exc
                # Prefer the provider's Retry-After when it is given; otherwise
                # fall back to a conservative exponential backoff (capped so we
                # never stall a request for minutes on a busy provider).
                backoff = _backoff_seconds(exc, attempt)
                self._log(
                    "warning",
                    "Transient Groq failure; retrying",
                    request_id=request_id,
                    error=type(exc).__name__,
                    attempt=attempt,
                    backoff=backoff,
                )
                await asyncio.sleep(backoff)
            except APIError as exc:
                # Non-transient provider errors (auth, permission, bad request,
                # server 5xx) are surfaced directly without retrying.
                translated = self._translate_error(exc, request_id)
                self._log(
                    "warning",
                    "Groq provider error",
                    request_id=request_id,
                    error=type(translated).__name__,
                )
                raise translated from exc

    # ------------------------------------------------------------------ #
    # public API
    # ------------------------------------------------------------------ #
    async def chat_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        model: str | None = None,
        seed: int | None = None,
    ) -> AICompletionResult:
        """Return a plain text completion for ``messages``."""
        request_id = self._new_request_id()
        client = self._require_client()
        self._log(
            "info",
            "Chat completion requested",
            request_id=request_id,
            model=model or self._model,
            messages=len(messages),
        )
        stream = False
        response: ChatCompletion = await self._run_with_retry(
            request_id,
            client.chat.completions.create,
            model=model or self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
            extra_headers={"X-CivicAgent-Request-Id": request_id},
            seed=seed,
        )
        text = _extract_text(response)
        return AICompletionResult(
            text=text,
            request_id=request_id,
            model=response.model,
            usage=_extract_usage(response),
        )

    async def structured_completion(
        self,
        messages: list[dict[str, str]],
        schema: type[_T],
        *,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
        seed: int | None = None,
    ) -> _T:
        """Request a Pydantic-validated structured response.

        The model is asked to return JSON matching ``schema``. Output is parsed
        with safe JSON repair; if it cannot be validated a
        :class:`AIStructuredParsingError` is raised (controlled human-review
        failure) rather than returning malformed data.
        """
        request_id = self._new_request_id()
        client = self._require_client()

        json_schema = schema.model_json_schema()
        self._log(
            "info",
            "Structured completion requested",
            request_id=request_id,
            model=model or self._model,
            schema_name=schema.__name__,
        )

        response: ChatCompletion = await self._run_with_retry(
            request_id,
            client.chat.completions.create,
            model=model or self._model,
            messages=_with_json_instructions(messages, schema, json_schema),
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            response_format={"type": "json_object"},
            extra_headers={"X-CivicAgent-Request-Id": request_id},
            seed=seed,
        )
        raw = _extract_text(response)
        return self._parse_structured(request_id, schema, raw)

    async def structured_vision_completion(
        self,
        content: list[dict[str, Any]],
        schema: type[_T],
        *,
        system_prompt: str | None = None,
        temperature: float = 0.0,
        max_tokens: int | None = None,
        model: str | None = None,
    ) -> _T:
        """Request a Pydantic-validated JSON response from a multimodal vision
        model (Groq, Part 8).

        ``content`` is an OpenAI-style content array that may include
        ``{"type": "image_url", "image_url": {"url": <data URI>}}`` parts plus
        ``{"type": "text", "text": ...}`` parts, allowing the model to "see"
        uploaded complaint images encoded as base64 data URIs.

        The request goes through the same retry/timeout/error handling as
        :meth:`structured_completion` and returns a Pydantic instance validated
        against ``schema``.
        """
        request_id = self._new_request_id()
        client = self._require_client()

        json_schema = schema.model_json_schema()
        _model = model or self._model
        self._log(
            "info",
            "Vision structured completion requested",
            request_id=request_id,
            model=_model,
            schema_name=schema.__name__,
            content_parts=len(content),
        )

        system_text = system_prompt or (
            "You must respond with valid JSON only, matching the following JSON Schema. "
            "Do not include markdown fences, commentary or anything outside the JSON object.\n\n"
            f"JSON Schema:\n{json_schema}"
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": content},
        ]

        response: ChatCompletion = await self._run_with_retry(
            request_id,
            client.chat.completions.create,
            model=_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            response_format={"type": "json_object"},
            extra_headers={"X-CivicAgent-Request-Id": request_id},
        )
        return self._parse_structured(request_id, schema, _extract_text(response))

    def _parse_structured(self, request_id: str, schema: type[_T], raw: str) -> _T:
        if not raw or not raw.strip():
            raise AIStructuredParsingError(
                f"Model returned an empty structured response (request {request_id})."
            )
        parsed: Any = None
        # Attempt 1: direct JSON load.
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = _repair_json(raw)

        if parsed is None:
            self._log(
                "warning",
                "Structured response was not valid JSON",
                request_id=request_id,
            )
            raise AIStructuredParsingError(
                f"Model returned malformed JSON that could not be repaired (request {request_id})."
            )

        # Attempt 2: validate against the schema.
        try:
            return schema.model_validate(parsed)
        except ValidationError as exc:
            # Last resort: if a single JSON object was quoted/escaped, try once more.
            if isinstance(parsed, dict):
                cleaned = {
                    k: (v if not isinstance(v, str) else _repair_inline(v))
                    for k, v in parsed.items()
                }
                try:
                    return schema.model_validate(cleaned)
                except ValidationError:
                    pass
            self._log(
                "warning",
                "Structured response failed schema validation",
                request_id=request_id,
                errors=str(exc),
            )
            raise AIStructuredParsingError(
                f"Model returned structured output that failed validation (request {request_id})."
            ) from exc

    async def stream_completion(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        model: str | None = None,
        seed: int | None = None,
    ) -> AsyncIterator[AIStreamChunk]:
        """Stream completion deltas from Groq."""
        request_id = self._new_request_id()
        client = self._require_client()
        self._log(
            "info",
            "Stream completion requested",
            request_id=request_id,
            model=model or self._model,
        )
        _model = model or self._model
        try:
            stream_resp = await client.chat.completions.create(
                model=_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                extra_headers={"X-CivicAgent-Request-Id": request_id},
                seed=seed,
            )
            async for chunk in stream_resp:  # type: ignore[union-attr]
                delta = _extract_delta(chunk)
                yield AIStreamChunk(
                    delta=delta,
                    request_id=request_id,
                    model=_model,
                    done=False,
                )
        except (RateLimitError, APITimeoutError, APIConnectionError) as exc:
            raise self._translate_error(exc, request_id) from exc
        except APIError as exc:
            raise self._translate_error(exc, request_id) from exc
        yield AIStreamChunk(delta="", request_id=request_id, model=_model, done=True)


# ---------------------------------------------------------------------- #
# module helpers
# ---------------------------------------------------------------------- #
def _extract_text(response: ChatCompletion) -> str:
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


def _extract_usage(response: ChatCompletion) -> AIUsage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    return AIUsage(
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
        total_tokens=getattr(usage, "total_tokens", None),
    )


def _extract_delta(chunk: ChatCompletionChunk) -> str:
    if not chunk.choices:
        return ""
    return chunk.choices[0].delta.content or ""


# Longest wait we will self-impose between automatic retries (limits how long a
# single AI call can stall under repeated 429 / 5xx pressure).
_MAX_AUTO_RETRY_BACKOFF = 15.0


def _retry_after_from(exc: APIError) -> float | None:
    """Parse Groq's ``Retry-After`` header (seconds or HTTP-date) when present."""
    try:
        headers = getattr(exc, "response", None) and getattr(exc.response, "headers", None)
        if not headers:
            return None
        header = headers.get("retry-after")
        if not header:
            try:
                header = headers["Retry-After"]
            except Exception:  # noqa: BLE001
                return None
        try:
            return max(0.0, float(str(header).strip().split(",")[0]))
        except ValueError:
            import datetime as _dt
            from email.utils import parsedate_to_datetime

            try:
                when = parsedate_to_datetime(str(header).strip())
                if when.tzinfo is None:
                    when = when.replace(tzinfo=_dt.UTC)

                return max(0.0, (when - _dt.datetime.now(_dt.UTC)).total_seconds())
            except Exception:  # noqa: BLE001
                return None
    except Exception:  # noqa: BLE001 - header parsing must never break a retry
        return None


def _backoff_seconds(exc: APIError, attempt: int) -> float:
    """Wait before the next automatic retry: Retry-After when available, else a
    conservative exponential backoff, capped at ``_MAX_AUTO_RETRY_BACKOFF``."""
    if isinstance(exc, RateLimitError):
        retry_after = _retry_after_from(exc)
        if retry_after is not None:
            return max(0.0, min(retry_after, 60.0))
    return min(0.5 * (2 ** (attempt - 1)), _MAX_AUTO_RETRY_BACKOFF)


def _with_json_instructions(
    messages: list[dict[str, str]],
    schema: type[_T],
    json_schema: dict[str, Any],
) -> list[dict[str, str]]:
    """Prepend a system message instructing the model to emit valid JSON."""
    instruction = (
        "You must respond with valid JSON only, matching the following JSON Schema. "
        "Do not include markdown fences, commentary or anything outside the JSON object.\n\n"
        f"JSON Schema:\n{json_schema}"
    )
    return [{"role": "system", "content": instruction}, *messages]


def _repair_json(raw: str) -> Any:
    """Best-effort JSON repair: strip fences/quotes and retry a plain parse."""
    candidates: list[str] = []
    stripped = raw.strip()
    # Remove markdown/json code fences.
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1]
        stripped = stripped.rsplit("```", 1)[0]
        stripped = stripped.strip()
    if stripped.startswith('"') and stripped.endswith('"'):
        stripped = stripped[1:-1]
        candidates.append(stripped)
    candidates.append(stripped)

    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _repair_inline(value: Any) -> Any:
    """Attempt to parse a string value that may itself be escaped JSON."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except Exception:
        return value


_ai_service: AIService | None = None


def get_ai_service(settings: Settings | None = None) -> AIService:
    """Return a process-wide :class:`AIService` singleton (test-overridable)."""
    global _ai_service
    if _ai_service is None:
        _ai_service = AIService(settings=settings)
    return _ai_service
