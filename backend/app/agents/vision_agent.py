"""AI Evidence Verification (Vision) Agent (Part 8).

The second LangGraph agent in CivicAgent. It runs the
``START → Vision → Validate → Persist → END`` graph to verify that a complaint's
uploaded images actually show the reported issue:

* **Vision** — loads the complaint's attached images from object storage, encodes
  them as base64 data URIs and sends them (with the complaint description) to the
  configured Groq multimodal model via a structured, Pydantic-validated call.
* **Validate** — enforces the :class:`VisionOutput` schema and routes low-confidence
  or mismatched results to human review. Malformed model output is retried; when the
  retry budget is exhausted it falls back to a human-review result so the run is
  *always* persisted with a valid (safe) result.
* **Persist** — records the run + trace events (``agent_runs`` / ``agent_events``,
  ``agent="vision"``) and advances the complaint to ``EVIDENCE_VERIFIED`` on success.
  It **never closes** the complaint and **never** auto-resolves it — mismatches and
  low-confidence results are routed to a human.

Safety rules:
  * Provider failures (timeout / rate limit / connection / config) and missing /
    corrupt / non-image evidence mark the run ``FAILED`` and leave the complaint
    intact so the caller can retry — Groq is never called directly from the UI.
  * A vision result is advisory only: the complaint status is advanced to
    ``EVIDENCE_VERIFIED`` (evidence reviewed) but is never closed based on it.
"""

from __future__ import annotations

import base64
import io
import logging
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from PIL import Image as PILImage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import AgentRun, Complaint, ComplaintMedia
from app.models.enums import AgentStatus, ComplaintStatus, TriageSeverity
from app.schemas.vision import VisionInput, VisionOutput
from app.services import agent_run_service
from app.services.ai_service import AIError, AIService, AIStructuredParsingError, get_ai_service
from app.services.complaint_service import record_status_transition
from app.storage import get_storage

logger = logging.getLogger(__name__)

AGENT_NAME = "vision"

# The retry budget for malformed / invalid model output. After this many
# consecutive failures to produce a valid VisionOutput the agent gives up and
# routes the result to human review rather than persisting bad data.
DEFAULT_MAX_VALIDATION_RETRIES = 2

# Max images forwarded in a single request (Groq vision limit).
MAX_IMAGES_PER_REQUEST = 5

# Messages shown / stored when a run fails for a data or provider reason.
_MSG_NO_IMAGES = "No image evidence is attached to this complaint to verify."
_MSG_INVALID_IMAGE = "An attached image could not be read as a valid image."
_MSG_NOT_IMAGE = "The complaint has no supported images to analyze."

# Fallback result used when the model cannot produce a valid VisionOutput even
# after retrying. It stays schema-valid and flags the complaint for a human.
_FALLBACK = VisionOutput(
    visual_evidence_detected=False,
    detected_issue="",
    severity=TriageSeverity.MEDIUM,
    confidence=0.0,
    evidence_description="Unable to verify visual evidence automatically; manual review required.",
    mismatch_detected=False,
    human_review_required=True,
)


class VisionState(TypedDict, total=False):
    """Graph state for the vision agent."""

    input: VisionInput
    output: VisionOutput | None
    attempt: int
    max_retries: int
    human_review: bool
    parse_error: bool  # True when the last vision call was un-parseable
    fatal_error: bool  # True when the last vision call was a provider failure
    error: str | None
    route: str  # routing decision produced by the validate node
    run: AgentRun
    db: AsyncSession
    ai: AIService
    model: str | None
    complaint_id: uuid.UUID
    duration_ms: int
    event_log: list[tuple[str, dict | None]]


# --------------------------------------------------------------------------- #
# Helpers for loading / validating images
# --------------------------------------------------------------------------- #
def _build_content_array(
    description: str, category: str | None, images: list[tuple[str, str]]
) -> list[dict[str, Any]]:
    """Build the OpenAI-style content array: text + ``image_url`` (data URI) parts.

    ``images`` is a list of ``(mime_type, bytes)`` pairs already validated.
    """
    complaint = "the reported civic issue"
    if category:
        complaint = f"the reported '{category}' complaint"
    text = (
        f'Complaint description: "{description}"\n\n'
        f"Inspect the attached photo(s). Determine whether they show evidence of {complaint}. "
        "Respond with the requested JSON object only."
    )
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    for mime, data in images:
        b64 = base64.b64encode(data).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
    return parts


def _validate_image_payload(data: bytes) -> str | None:
    """Return an error string if ``data`` is not a decodable image, else None."""
    if not data:
        return "Image payload is empty."
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            img.verify()
        return None
    except Exception:
        return "Image payload is not a valid, decodable image."


# --------------------------------------------------------------------------- #
# Graph nodes
# --------------------------------------------------------------------------- #
async def _vision_node(state: VisionState) -> dict[str, Any]:
    """Load the complaint images, call the multimodal model, and record why we
    fail when evidence is missing/invalid or the provider is unreachable."""
    attempt = state.get("attempt", 0) + 1
    input_data: VisionInput = state["input"]
    ai: AIService = state["ai"]
    run: AgentRun = state["run"]
    db: AsyncSession = state["db"]

    await agent_run_service._append_event(
        state["db"],
        run,
        "vision.started",
        {"attempt": attempt, "image_keys": len(input_data.image_keys)},
    )

    # --- Load & validate images from storage. ---
    images: list[tuple[str, bytes]] = []
    for key in input_data.image_keys[:MAX_IMAGES_PER_REQUEST]:
        try:
            media = await db.scalar(select(ComplaintMedia).where(ComplaintMedia.storage_key == key))
        except Exception:  # noqa: BLE001 - unexpected DB error
            media = None
        if media is None:
            return {
                "output": None,
                "attempt": attempt,
                "parse_error": False,
                "fatal_error": True,
                "error": "One of the attached images no longer exists in storage.",
                "human_review": False,
            }
        try:
            data = get_storage().read(media.storage_key)
        except Exception as exc:  # noqa: BLE001 - storage read failure
            logger.error("Vision image read failed for %s: %s", key, exc)
            return {
                "output": None,
                "attempt": attempt,
                "parse_error": False,
                "fatal_error": True,
                "error": _MSG_INVALID_IMAGE,
                "human_review": False,
            }
        problem = _validate_image_payload(data)
        if problem is not None:
            return {
                "output": None,
                "attempt": attempt,
                "parse_error": False,
                "fatal_error": True,
                "error": problem,
                "human_review": False,
            }
        images.append((media.content_type, data))

    if not images:
        return {
            "output": None,
            "attempt": attempt,
            "parse_error": False,
            "fatal_error": True,
            "error": _MSG_NO_IMAGES,
            "human_review": False,
        }

    content = _build_content_array(input_data.description, input_data.category, images)
    try:
        output: VisionOutput = await ai.structured_vision_completion(
            content,
            VisionOutput,
            system_prompt=(
                "You are a municipal evidence-verification assistant. Given a complaint "
                "description and attached photo(s), judge whether the image shows evidence "
                "of the reported issue. Be objective. If the image shows the issue, set "
                "visual_evidence_detected=true and describe what you see in "
                "evidence_description. If the images do not match the report (or show "
                "something unrelated), set mismatch_detected=true. Set confidence to how "
                "sure you are (0..1). Respond only with valid JSON matching the schema."
            ),
            model=state["model"],
        )
        return {
            "output": output,
            "attempt": attempt,
            "parse_error": False,
            "fatal_error": False,
            "error": None,
            "human_review": bool(output.human_review_required),
        }
    except AIStructuredParsingError as exc:
        logger.warning("Vision output invalid (attempt %s): %s", attempt, exc)
        return {
            "output": None,
            "attempt": attempt,
            "parse_error": True,
            "fatal_error": False,
            "error": str(exc),
            "human_review": False,
        }
    except AIError as exc:  # provider failure: timeout / rate limit / config / api
        logger.error("Vision provider failure (attempt %s): %s", attempt, exc)
        return {
            "output": None,
            "attempt": attempt,
            "parse_error": False,
            "fatal_error": True,
            "error": str(exc),
            "human_review": False,
        }


def _validate_node(state: VisionState) -> dict[str, Any]:
    """Report the routing decision after a vision attempt."""
    events: list[tuple[str, dict | None]] = state.get("event_log", [])

    if state.get("fatal_error"):
        events.append(("validate.provider_failed", {"error": state.get("error")}))
        return {"event_log": events, "route": "fail"}

    if state.get("output") is None and state.get("parse_error"):
        if state.get("attempt", 0) < state.get("max_retries", DEFAULT_MAX_VALIDATION_RETRIES):
            events.append(("validate.retrying", {"attempt": state.get("attempt")}))
            return {"event_log": events, "route": "retry"}
        events.append(
            (
                "validate.exhausted",
                {"attempt": state.get("attempt"), "human_review": True},
            )
        )
        return {
            "event_log": events,
            "output": _FALLBACK,
            "human_review": True,
            "route": "persist",
        }

    output: VisionOutput | None = state.get("output")
    # Flag low confidence or mismatch for human review regardless of schema flag.
    low_conf = output is not None and output.confidence < 0.5
    needs_review = output is not None and (
        output.human_review_required or low_conf or output.mismatch_detected
    )
    if needs_review:
        assert output is not None
        # Persist a schema-safe result that explicitly requires human review.
        reviewed = output.model_copy(update={"human_review_required": True})
        events.append(
            (
                "validate.human_review",
                {
                    "attempt": state.get("attempt"),
                    "low_conf": low_conf,
                    "mismatch": bool(output.mismatch_detected),
                },
            )
        )
        return {
            "event_log": events,
            "output": reviewed,
            "human_review": True,
            "route": "persist",
        }

    events.append(
        (
            "validate.passed",
            {
                "attempt": state.get("attempt"),
                "confidence": _conf(output),
            },
        )
    )
    return {"event_log": events, "route": "persist"}


async def _persist_node(state: VisionState) -> dict[str, Any]:
    """Persist the run + trace events and advance the complaint status."""
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = state.get("fatal_error", False)

    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED
    await agent_run_service.finalize_run(
        db,
        run,
        status=status,
        result=_fallback_if_invalid_state(state) if not failed else None,
        error=state.get("error") if failed else None,
        duration_ms=state.get("duration_ms"),
        events=events,
    )
    # On success we only advance the complaint to EVIDENCE_VERIFIED — we never
    # close or resolve it based on vision output. On failure we leave it as-is.
    if not failed:
        await _transition_complaint(
            db,
            state["complaint_id"],
            ComplaintStatus.EVIDENCE_VERIFIED,
            note="AI evidence verification completed.",
        )
    return {}


def _fallback_if_invalid_state(state: VisionState) -> VisionOutput | None:
    output = state.get("output")
    return output if output is not None else _FALLBACK


def _should_route_to(state: VisionState) -> str:
    return state.get("route", "persist")


# --------------------------------------------------------------------------- #
# Graph building
# --------------------------------------------------------------------------- #
def build_graph() -> Any:
    """Build the ``START → Vision → Validate → Persist → END`` LangGraph state graph."""
    graph = StateGraph(VisionState)
    graph.add_node("vision", _vision_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("persist", _persist_node)

    graph.add_edge(START, "vision")
    graph.add_edge("vision", "validate")
    graph.add_conditional_edges(
        "validate",
        _should_route_to,
        {"vision": "vision", "persist": "persist", "fail": "persist", "retry": "vision"},
    )
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Public runner
# --------------------------------------------------------------------------- #
class VisionAgent:
    """Orchestrator that runs the vision evidence-verification graph."""

    def __init__(
        self,
        *,
        ai: AIService | None = None,
        settings: Settings | None = None,
        max_validation_retries: int = DEFAULT_MAX_VALIDATION_RETRIES,
        graph: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._ai = ai or get_ai_service(self._settings)
        self._max_retries = max_validation_retries
        self._graph = graph if graph is not None else build_graph()

    def _resolve_model(self) -> str | None:
        model = (self._settings.VISION_MODEL or "").strip() or (
            self._settings.GROQ_MODEL or ""
        ).strip()
        return model or None

    async def run(
        self,
        db: AsyncSession,
        *,
        complaint_id: uuid.UUID,
        input_data: VisionInput,
    ) -> AgentRun:
        """Create a run, execute the graph end-to-end, and return the persisted run."""
        started = time.monotonic()
        model = self._resolve_model()
        run = await agent_run_service.create_run(
            db,
            complaint_id=complaint_id,
            agent=AGENT_NAME,
            model=model,
        )
        await agent_run_service._append_event(db, run, "run.started", {"agent": AGENT_NAME})
        await db.commit()
        run_id = run.id

        state: VisionState = {
            "input": input_data,
            "output": None,
            "attempt": 0,
            "max_retries": self._max_retries,
            "human_review": False,
            "parse_error": False,
            "fatal_error": False,
            "error": None,
            "route": "pending",
            "run": run,
            "db": db,
            "ai": self._ai,
            "model": model,
            "complaint_id": complaint_id,
            "duration_ms": None,
            "event_log": [],
        }
        await self._graph.ainvoke(state)

        duration = int((time.monotonic() - started) * 1000)
        reloaded = await agent_run_service.get_run_with_events(db, run_id)
        if reloaded is not None and reloaded.duration_ms is None:
            reloaded.duration_ms = duration
            await db.commit()
        return reloaded or run


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _conf(output: VisionOutput | None) -> float | None:
    return None if output is None else output.confidence


async def _transition_complaint(
    db: AsyncSession,
    complaint_id: uuid.UUID,
    new_status: ComplaintStatus,
    *,
    note: str,
) -> None:
    """Set a complaint status and append an automated (system) timeline entry."""
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        logger.warning("Vision persist: complaint %s no longer exists", complaint_id)
        return
    if complaint.status == new_status:
        return
    complaint.status = new_status
    db.add(record_status_transition(complaint, new_status, actor_id=None, note=note))
