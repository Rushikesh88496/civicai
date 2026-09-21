"""Central Groq AI integration layer (Part 6).

Provides chat, structured (Pydantic-validated) and streaming completions with
retries, timeouts, rate-limit handling, connection-error handling, structured
logging, per-call request IDs and model configuration.

The provider key is read only from environment configuration (``Settings``);
it is never logged and never exposed to the browser.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
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
from PIL import Image
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_T = TypeVar("_T", bound=BaseModel)

# How long a Groq model-list snapshot is trusted before re-fetching.
_MODEL_LIST_TTL_SECONDS = 300.0
# How long a confirmed vision-capable probe for a given model id is trusted
# (set to a day; the list snapshot above still re-validates accessibility).
VISION_PROBE_TTL_SECONDS = 86400.0


class AIError(Exception):
    """Base class for controlled AI-service failures."""


class AIConfigurationError(AIError):
    """Raised when no Groq API key is configured (or the key is invalid)."""


class AIModelNotFoundError(AIError):
    """Raised when Groq does not know the requested model (``model_not_found``).

    This is a configuration problem, not a verdict on the analysed content: the
    fix is a correct model id, never a fabricated AI result.
    """


class AIModelAccessDeniedError(AIError):
    """Raised when the configured model exists but the current account is not
    authorized to run it (``model_access_denied`` / 403)."""


class AIMultimodalUnsupportedError(AIError):
    """Raised when the configured model exists but does not accept image input.

    Only a multimodal model may be used for evidence verification — a text-only
    model must never be silently substituted.
    """


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
class VisionReadiness:
    """Result of the pre-flight check for a vision-capable model.

    ``ok`` is True only when the model is configured, accessible to the current
    Groq account AND has just been probed to accept image input (or a previous
    probe is still cached). ``error`` carries a stable token the agents map to a
    structured, user-safe failure:
    ``no_api_key`` | ``model_unset`` | ``model_not_found`` |
    ``model_access_denied`` | ``model_not_vision`` | ``provider_unavailable``.
    """

    ok: bool
    model: str | None = None
    error: str | None = None


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


def _first_error(detail: object) -> str:
    """Best-effort extraction of the provider's human-readable error message."""
    if isinstance(detail, dict):
        error = detail.get("error") or detail
        if isinstance(error, dict):
            message = error.get("message") or error.get("code")
            if message:
                return str(message)
        if detail.get("message"):
            return str(detail["message"])
    return str(detail)[:200]


def _readiness_exception(token: str | None, model: str | None) -> AIError:
    """Map a :class:`VisionReadiness` error token to a structured AI exception."""
    name = model or "the configured vision model"
    if token == "model_not_found":
        return AIModelNotFoundError(
            f"Groq does not serve {name!r} (model_not_found). Configure an "
            "accessible vision model via VISION_MODEL."
        )
    if token == "model_access_denied":
        return AIModelAccessDeniedError(
            f"Groq refuses to run {name!r} for this account (model_access_denied)."
        )
    if token == "model_not_vision":
        return AIMultimodalUnsupportedError(
            f"{name!r} does not accept image input; choose a multimodal (VL) model."
        )
    return AIConfigurationError(
        "Groq vision is not configured. Set GROQ_API_KEY and VISION_MODEL."
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
        self._model_list_cache: tuple[float, list[str]] | None = None
        self._vision_probe_cache: dict[str, tuple[float, bool]] = {}

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
                code = error.get("code") or error.get("type")
        status = int(getattr(exc, "status_code", 0) or 0)
        if code == "model_not_found" or status == 404:
            # Account cannot use this model id (unknown or withdrawn model).
            return AIModelNotFoundError(
                f"Groq cannot run the configured model (request {request_id}): "
                f"{_first_error(detail)}"
            )
        if code in ("model_access_denied", "permission_denied") or status == 403:
            return AIModelAccessDeniedError(
                f"Groq denied access to the configured model for this account "
                f"(request {request_id})."
            )
        if code in ("invalid_api_key", "authentication_error") or status == 401:
            return AIConfigurationError(
                "Groq rejected the configured API key. Check GROQ_API_KEY."
            )
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

    # ------------------------------------------------------------------ #
    # Model access & vision pre-flight
    # ------------------------------------------------------------------ #
    async def list_models(self, *, force: bool = False) -> list[str]:
        """Return the model ids accessible to the current Groq account.

        A fresh ``models.list`` result is cached for ``_MODEL_LIST_TTL_SECONDS``
        so handling verification requests does not hammer the provider. When a
        transient failure hits and a snapshot exists, the stale snapshot is
        served rather than blocking verification.
        """
        client = self._require_client()
        now = time.monotonic()
        cached = self._model_list_cache
        if not force and cached and (now - cached[0]) < _MODEL_LIST_TTL_SECONDS:
            return cached[1]
        request_id = self._new_request_id()
        self._log("info", "Groq model list requested", request_id=request_id)
        try:
            listing = await self._run_with_retry(request_id, client.models.list)
        except AIError:
            if cached:
                return cached[1]
            raise
        models = [
            getattr(model, "id", None)
            for model in (getattr(listing, "data", None) or [])
        ]
        snapshot = [model for model in models if model]
        self._model_list_cache = (now, snapshot)
        return snapshot

    async def _probe_vision(self, model: str) -> bool:
        """Ask the model to describe a tiny image; ``True`` means it accepts
        visual input. Spec failures (wrong model / denied) propagate so callers
        can classify them instead of hiding them."""
        cached = self._vision_probe_cache.get(model)
        now = time.monotonic()
        if cached and (now - cached[0]) < VISION_PROBE_TTL_SECONDS:
            return cached[1]
        client = self._require_client()
        request_id = self._new_request_id()
        buffer = io.BytesIO()
        Image.new("RGB", (16, 16), color=(40, 60, 80)).save(buffer, format="PNG")
        data_uri = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")
        content: list[dict[str, Any]] = [
            {"type": "text", "text": "Reply with the single word: ok"},
            {"type": "image_url", "image_url": {"url": data_uri}},
        ]
        try:
            await self._run_with_retry(
                request_id,
                client.chat.completions.create,
                model=model,
                messages=[{"role": "user", "content": content}],
                max_tokens=4,
                stream=False,
            )
            self._vision_probe_cache[model] = (now, True)
            return True
        except AIModelNotFoundError:
            raise
        except AIModelAccessDeniedError:
            raise
        except AIError as exc:
            if "must be a string" in str(exc):
                # Provider refuses image content entirely: a text-only model.
                return False
            raise

    async def vision_readiness(self, model: str | None = None) -> VisionReadiness:
        """Pre-flight check before sending user-provided images to Groq.

        Verifies, in order: an API key exists, the model id is non-empty, the
        model is in the account's accessible model list (with a live retrieve
        fallback to distinguish ``model_not_found`` from ``model_access_denied``)
        and a tiny image probe succeeds. Failures are summarized as a stable
        ``error`` token, never as an AI verdict.
        """
        if self._client is None:
            return VisionReadiness(ok=False, model=model, error="no_api_key")
        target = (model or "").strip() or (self._model or "").strip()
        if not target:
            return VisionReadiness(ok=False, model=None, error="model_unset")
        try:
            models = await self.list_models()
        except AIError as exc:
            tokens = {
                AIConfigurationError: "no_api_key",
                AIConnectionError: "provider_unavailable",
                AITimeoutError: "provider_unavailable",
                AIRateLimitError: "provider_unavailable",
            }
            return VisionReadiness(
                ok=False, model=target, error=tokens.get(type(exc), "provider_unavailable")
            )
        if target not in models:
            try:
                await self._run_with_retry(
                    self._new_request_id(), self._require_client().models.retrieve, target
                )
            except AIModelNotFoundError:
                return VisionReadiness(ok=False, model=target, error="model_not_found")
            except AIModelAccessDeniedError:
                return VisionReadiness(ok=False, model=target, error="model_access_denied")
            except AIError:
                return VisionReadiness(ok=False, model=target, error="provider_unavailable")
        try:
            vision = await self._probe_vision(target)
        except AIModelNotFoundError:
            return VisionReadiness(ok=False, model=target, error="model_not_found")
        except AIModelAccessDeniedError:
            return VisionReadiness(ok=False, model=target, error="model_access_denied")
        except (AIRateLimitError, AITimeoutError, AIConnectionError):
            # Transient provider problem: don't block the attempt; the actual
            # verification call classifies and reports it without faking output.
            vision = True
        except AIError:
            vision = True
        if not vision:
            return VisionReadiness(ok=False, model=target, error="model_not_vision")
        return VisionReadiness(ok=True, model=target, error=None)

    async def ensure_vision_ready(self, model: str | None = None) -> None:
        """Raise a structured AI exception when the vision setup is not ready."""
        readiness = await self.vision_readiness(model)
        if readiness.ok:
            return
        raise _readiness_exception(readiness.error, readiness.model)


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
