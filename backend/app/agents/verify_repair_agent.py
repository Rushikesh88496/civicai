"""AI Resolution Verification Agent (Part 19).

Verifies whether a completed work order's repair actually resolved the reported
issue by running the ``START → Verify → Validate → Persist → END`` LangGraph:

* **Verify** — loads the work order's BEFORE / AFTER evidence photos from object
  storage, validates they are decodable images, and forwards them (with the
  original complaint description) to the configured Groq multimodal model via a
  structured, Pydantic-validated vision call.
* **Validate** — applies the deterministic safety gates (Part 19):
    * an *unchanged* AFTER photo (pixel-identical to the BEFORE photo) is
      short-circuited to ``NOT_RESOLVED`` *without any AI call* (deterministic
      pixel-diff guard);
    * low-confidence or malformed model output is forced to
      ``NEEDS_HUMAN_REVIEW``;
    * every ``PARTIALLY_RESOLVED`` / ``NOT_RESOLVED`` outcome requires human
      review;
    * a critical-priority (P1_CRITICAL) order requires an authorized human
      sign-off even for high-confidence ``VERIFIED`` results (configured
      human-approval rule);
    * after exhausting its retry budget for invalid output the agent persists a
      schema-safe ``NEEDS_HUMAN_REVIEW`` fallback.
* **Persist** — writes a dedicated ``work_order_verifications`` row (the AI
  result is advisory and always reviewable by staff) plus the agent run + trace
  events (``agent_runs`` / ``agent_events``, ``agent="verify_repair"``).

Safety rules:
  * Provider failures (timeout / rate limit / connection / config) and missing /
    corrupt evidence mark the run ``FAILED`` and persist **no** verdict, so a
    bad result can never slip through. Groq is never called from the UI directly.
  * The agent NEVER auto-closes or auto-reopens an order: negative or
    low-confidence outcomes are surfaced for an authorized human (officer /
    ward rep / admin) to review and act on.
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
from app.models import AgentRun, ComplaintMedia, WorkOrderPhoto, WorkOrderVerification
from app.models.enums import AgentStatus, VerificationStatus
from app.schemas.verification import VerificationInput, VerificationOutput
from app.services import agent_run_service
from app.services.ai_service import (
    AIAPIError,
    AIError,
    AIService,
    AIStructuredParsingError,
    get_ai_service,
)
from app.storage import get_storage

logger = logging.getLogger(__name__)

AGENT_NAME = "verify_repair"

# Retry budget for malformed / invalid model output before routing to human
# review (mirrors the vision agent's safety behaviour).
DEFAULT_MAX_VALIDATION_RETRIES = 2

# Thumbnail size (px) used by the deterministic unchanged-photo guard.
_PIXEL_THUMB = 128

# Messages stored when a run fails for a data or provider reason.
_MSG_MISSING_IMAGES = (
    "Missing evidence photo; both a BEFORE and an AFTER photo are required to verify the repair."
)
_MSG_INVALID_IMAGE = "An evidence photo could not be read as a valid image."

# Deterministic outcome when the AFTER photo is identical to the BEFORE photo:
# no AI call is needed — the repair is visibly not done.
_UNCHANGED_OUTPUT = VerificationOutput(
    repair_evidence=(
        "The AFTER photo is pixel-identical to the BEFORE photo — no repair is visible."
    ),
    remaining_issue=(
        "The reported issue appears unresolved; there is no visible change between "
        "the before and after photos."
    ),
    confidence=1.0,
    verification_status=VerificationStatus.NOT_RESOLVED,
    issue_fixed=False,
    human_review_required=True,
)

# Fallback result used when the model cannot produce a valid VerificationOutput
# even after retrying. It stays schema-valid and flags the case for a human.
_FALLBACK = VerificationOutput(
    repair_evidence="",
    remaining_issue="The repair could not be assessed automatically; manual review required.",
    confidence=0.0,
    verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
    issue_fixed=False,
    human_review_required=True,
)


class VerifyState(TypedDict, total=False):
    """Graph state for the resolution-verification agent."""

    input: VerificationInput
    work_order_id: uuid.UUID
    complaint_id: uuid.UUID
    output: VerificationOutput | None
    attempt: int
    max_retries: int
    human_review: bool
    parse_error: bool  # True when the last verify call was un-parseable
    fatal_error: bool  # True when evidence/provider failure (no verdict)
    error: str | None
    route: str
    source: str  # "groq" | "pixel-diff"
    critical: bool
    low_confidence_threshold: float
    verified_min_confidence: float
    run: AgentRun
    db: AsyncSession
    ai: AIService
    model: str | None
    duration_ms: int
    event_log: list[tuple[str, dict | None]]


# --------------------------------------------------------------------------- #
# Helpers for loading / comparing / validating photos
# --------------------------------------------------------------------------- #
def _build_content_array(
    description: str,
    category: str | None,
    images: list[tuple[str, bytes]],
    *,
    completion_notes: str | None = None,
    complaint_image: tuple[str, bytes] | None = None,
) -> list[dict[str, Any]]:
    """Build the OpenAI-style content array: text + ``image_url`` (data URI) parts.

    ``images`` is ``[(mime_type, bytes)]``; the BEFORE photo is sent first, then
    the AFTER photo so the model can compare them in order. When a citizen
    attached an original complaint photo (``complaint_image``) it is sent first
    so the model can compare the reported condition against the evidence; the
    worker's ``completion_notes`` are included as text context.
    """
    issue = "the reported civic issue"
    if category:
        issue = f"the reported '{category}' complaint"
    notes = f"\n\nThe field worker's completion notes: \"{completion_notes}\"" if completion_notes else ""
    complaint_photo_hint = (
        "\n\nThe first image is the citizen's ORIGINAL complaint photo (the reported "
        "condition); compare it against the before/after evidence."
        if complaint_image is not None
        else ""
    )
    text = (
        f'Original complaint description: "{description}"{notes}\n\n'
        f"Inspect the attached photos in order:{complaint_photo_hint} The BEFORE "
        f"photo (taken before the repair) and the AFTER photo (second, taken by a "
        f"field worker after attempting to resolve {issue}). Determine whether the "
        f"AFTER photo shows the issue is resolved. Fill repair_evidence with what "
        f"you observe that shows the fix, remaining_issue with anything still "
        f"unresolved, and set issue_fixed=true when the reported issue is gone. "
        "Respond with the requested JSON object only."
    )
    parts: list[dict[str, Any]] = [{"type": "text", "text": text}]
    if complaint_image is not None:
        mime, data = complaint_image
        b64 = base64.b64encode(data).decode("ascii")
        parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
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


def _images_identical(before_data: bytes, after_data: bytes) -> bool:
    """Return True when the two photos are byte- or pixel-identical.

    Byte equality catches the same file uploaded twice. For visually identical
    re-uploads we compare small RGB thumbnails (cheap, bounded memory) so minor
    encoding differences do not hide an unchanged scene.
    """
    if before_data == after_data:
        return True
    try:
        with (
            PILImage.open(io.BytesIO(before_data)) as b_img,
            PILImage.open(io.BytesIO(after_data)) as a_img,
        ):
            b = b_img.convert("RGB").resize((_PIXEL_THUMB, _PIXEL_THUMB))
            a = a_img.convert("RGB").resize((_PIXEL_THUMB, _PIXEL_THUMB))
            return b.tobytes() == a.tobytes()
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# Graph nodes
# --------------------------------------------------------------------------- #
def _fatal(state: VerifyState, attempt: int, error: str) -> dict[str, Any]:
    return {
        "output": None,
        "attempt": attempt,
        "parse_error": False,
        "fatal_error": True,
        "error": error,
        "human_review": False,
    }


async def _verify_node(state: VerifyState) -> dict[str, Any]:
    """Load the BEFORE / AFTER photos, run the (optional) deterministic guard,
    then call the multimodal model and record why we fail when evidence is
    missing/invalid or the provider is unreachable."""
    attempt = state.get("attempt", 0) + 1
    input_data: VerificationInput = state["input"]
    ai: AIService = state["ai"]
    run: AgentRun = state["run"]
    db: AsyncSession = state["db"]

    await agent_run_service._append_event(
        state["db"],
        run,
        "verify.started",
        {
            "attempt": attempt,
            "before_key": input_data.before_key,
            "after_key": input_data.after_key,
        },
    )

    # --- Load & validate both evidence photos from storage (order matters). ---
    images: list[tuple[str, bytes]] = []
    for label, key in (("BEFORE", input_data.before_key), ("AFTER", input_data.after_key)):
        if not key:
            return _fatal(state, attempt, _MSG_MISSING_IMAGES)
        try:
            media = await db.scalar(select(WorkOrderPhoto).where(WorkOrderPhoto.storage_key == key))
        except Exception:  # noqa: BLE001 - unexpected DB error
            media = None
        if media is None:
            return _fatal(state, attempt, _MSG_MISSING_IMAGES)
        try:
            data = get_storage().read(media.storage_key)
        except Exception as exc:  # noqa: BLE001 - storage read failure
            logger.error("Verify photo read failed for %s: %s", key, exc)
            return _fatal(state, attempt, _MSG_INVALID_IMAGE)
        problem = _validate_image_payload(data)
        if problem is not None:
            return _fatal(state, attempt, problem)
        images.append((media.content_type, data))
        # First image loaded is BEFORE; use it for the unchanged guard.
        if label == "BEFORE":
            before_data = data
        else:
            if _images_identical(before_data, data):
                return {
                    "output": _UNCHANGED_OUTPUT,
                    "attempt": attempt,
                    "parse_error": False,
                    "fatal_error": False,
                    "error": None,
                    "human_review": True,
                    "source": "pixel-diff",
                }

    # --- Load & validate the original complaint photo (optional, best-effort). ---
    complaint_image: tuple[str, bytes] | None = None
    if input_data.original_complaint_key:
        try:
            comp_media = await db.scalar(
                select(ComplaintMedia).where(
                    ComplaintMedia.storage_key == input_data.original_complaint_key
                )
            )
        except Exception:  # noqa: BLE001 - unexpected DB error
            comp_media = None
        if comp_media is not None:
            try:
                comp_data = get_storage().read(comp_media.storage_key)
                if _validate_image_payload(comp_data) is None:
                    complaint_image = (comp_media.content_type, comp_data)
            except Exception as exc:  # noqa: BLE001 - best-effort; do not block the run
                logger.warning("Verify original complaint photo read failed: %s", exc)

    content = _build_content_array(
        input_data.complaint_description,
        input_data.category,
        images,
        completion_notes=input_data.completion_notes,
        complaint_image=complaint_image,
    )
    try:
        output: VerificationOutput = await ai.structured_vision_completion(
            content,
            VerificationOutput,
            system_prompt=(
                "You are a municipal repair-verification assistant. Given an original "
                "complaint description, a BEFORE photo taken before the repair and an "
                "AFTER photo taken after the repair attempt, judge whether the reported "
                "issue has actually been resolved. verification_status must be VERIFIED "
                "when the AFTER photo shows the issue is fixed; PARTIALLY_RESOLVED when "
                "it is visibly improved but not fully fixed; NOT_RESOLVED when the AFTER "
                "photo still shows the reported issue (or shows no change). Set "
                "repair_evidence to what specifically confirms the fix, remaining_issue "
                "to anything that still looks broken, and issue_fixed=true only when the "
                "reported issue is resolved. Set confidence to how sure you are (0..1). "
                "Respond only with valid JSON matching the schema."
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
        logger.warning("Verify output invalid (attempt %s): %s", attempt, exc)
        return {
            "output": None,
            "attempt": attempt,
            "parse_error": True,
            "fatal_error": False,
            "error": str(exc),
            "human_review": False,
        }
    except AIAPIError as exc:
        # A server-side JSON-rejection (the copied / similar evidence is fine,
        # but the provider rejected the model's generated JSON) is treated like
        # an un-parseable output: retry, then route to human review. Any other
        # provider failure stays fatal (no verdict is persisted).
        if exc.code == "json_validate_failed":
            logger.warning("Verify JSON rejected by provider (attempt %s): %s", attempt, exc)
            return {
                "output": None,
                "attempt": attempt,
                "parse_error": True,
                "fatal_error": False,
                "error": str(exc),
                "human_review": False,
            }
        logger.error("Verify provider failure (attempt %s): %s", attempt, exc)
        return _fatal(state, attempt, str(exc))
    except AIError as exc:  # timeout / rate limit / connection / config
        logger.error("Verify provider failure (attempt %s): %s", attempt, exc)
        return _fatal(state, attempt, str(exc))


def _validate_node(state: VerifyState) -> dict[str, Any]:
    """Apply the deterministic safety gates and report the routing decision."""
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

    output: VerificationOutput | None = state.get("output")
    if output is None:
        events.append(("validate.unknown", {}))
        return {
            "event_log": events,
            "output": _FALLBACK,
            "human_review": True,
            "route": "persist",
        }

    low_conf = output.confidence < state.get(
        "low_confidence_threshold", get_settings().VERIFICATION_LOW_CONFIDENCE
    )
    status = output.verification_status
    review = bool(output.human_review_required)

    if state.get("source") == "pixel-diff":
        status = VerificationStatus.NOT_RESOLVED
        review = True
        events.append(("validate.unchanged_photo", {"confidence": output.confidence}))
    elif status == VerificationStatus.NEEDS_HUMAN_REVIEW:
        review = True
    elif low_conf:
        status = VerificationStatus.NEEDS_HUMAN_REVIEW
        review = True
    elif status == VerificationStatus.VERIFIED and output.confidence < state.get(
        "verified_min_confidence", get_settings().VERIFICATION_VERIFIED_MIN_CONFIDENCE
    ):
        status = VerificationStatus.NEEDS_HUMAN_REVIEW
        review = True

    if status in (
        VerificationStatus.PARTIALLY_RESOLVED,
        VerificationStatus.NOT_RESOLVED,
    ):
        review = True

    if state.get("critical"):
        review = True
        events.append(("validate.critical_review", {"priority": state["input"].priority_bucket}))

    enforced = output.model_copy(
        update={"verification_status": status, "human_review_required": review}
    )

    if review:
        events.append(
            (
                "validate.human_review",
                {
                    "attempt": state.get("attempt"),
                    "low_conf": low_conf,
                    "status": status.value,
                },
            )
        )
    else:
        events.append(
            (
                "validate.passed",
                {"attempt": state.get("attempt"), "confidence": output.confidence},
            )
        )
    return {"event_log": events, "output": enforced, "human_review": review, "route": "persist"}


async def _persist_node(state: VerifyState) -> dict[str, Any]:
    """Persist the run + trace events and the dedicated verification row."""
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = state.get("fatal_error", False)

    if not failed and state.get("output") is not None:
        output: VerificationOutput = state["output"]
        db.add(
            WorkOrderVerification(
                work_order_id=state["work_order_id"],
                complaint_id=state["complaint_id"],
                before_photo_id=state["input"].before_photo_id,
                after_photo_id=state["input"].after_photo_id,
                repair_evidence=output.repair_evidence or None,
                remaining_issue=output.remaining_issue or None,
                confidence=output.confidence,
                verification_status=output.verification_status,
                human_review_required=output.human_review_required,
                source=state.get("source", "groq"),
            )
        )

    status = AgentStatus.FAILED if failed else AgentStatus.SUCCEEDED
    await agent_run_service.finalize_run(
        db,
        run,
        status=status,
        result=state.get("output") if not failed else None,
        error=state.get("error") if failed else None,
        duration_ms=state.get("duration_ms"),
        events=events,
    )
    return {}


def _should_route_to(state: VerifyState) -> str:
    return state.get("route", "persist")


# --------------------------------------------------------------------------- #
# Graph building
# --------------------------------------------------------------------------- #
def build_graph() -> Any:
    """Build the ``START → Verify → Validate → Persist → END`` LangGraph state graph."""
    graph = StateGraph(VerifyState)
    graph.add_node("verify", _verify_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("persist", _persist_node)

    graph.add_edge(START, "verify")
    graph.add_edge("verify", "validate")
    graph.add_conditional_edges(
        "validate",
        _should_route_to,
        {"verify": "verify", "persist": "persist", "fail": "persist", "retry": "verify"},
    )
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Public runner
# --------------------------------------------------------------------------- #
class VerifyRepairAgent:
    """Orchestrator that runs the AI resolution-verification graph."""

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
        model = (
            (self._settings.VERIFICATION_MODEL or "").strip()
            or (self._settings.VISION_MODEL or "").strip()
            or (self._settings.GROQ_MODEL or "").strip()
        )
        return model or None

    @staticmethod
    def _is_critical(input_data: VerificationInput, settings: Settings | None = None) -> bool:
        cfg = settings or get_settings()
        priority = input_data.priority_bucket or ""
        return cfg.VERIFICATION_HUMAN_REVIEW_CRITICAL and priority.startswith("P1")

    async def run(
        self,
        db: AsyncSession,
        *,
        work_order_id: uuid.UUID,
        complaint_id: uuid.UUID,
        input_data: VerificationInput,
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

        state: VerifyState = {
            "input": input_data,
            "work_order_id": work_order_id,
            "complaint_id": complaint_id,
            "output": None,
            "attempt": 0,
            "max_retries": self._max_retries,
            "human_review": False,
            "parse_error": False,
            "fatal_error": False,
            "error": None,
            "route": "pending",
            "source": "groq",
            "critical": self._is_critical(input_data, self._settings),
            "low_confidence_threshold": self._settings.VERIFICATION_LOW_CONFIDENCE,
            "verified_min_confidence": self._settings.VERIFICATION_VERIFIED_MIN_CONFIDENCE,
            "run": run,
            "db": db,
            "ai": self._ai,
            "model": model,
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


__all__ = [
    "AGENT_NAME",
    "DEFAULT_MAX_VALIDATION_RETRIES",
    "VerifyRepairAgent",
    "build_graph",
]
