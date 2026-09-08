"""AI Triage Agent (Part 7).

The first real LangGraph agent in CivicAgent. It runs the
``START → Triage → Validate → Persist → END`` graph to turn a raw complaint into
a validated triage decision:

* **Triage**  — calls the centralized Groq ``AIService`` for a structured
  ``TriageOutput``.
* **Validate** — enforces the output schema. If the model returns malformed or
  un-parseable output it retries; once the retry budget is spent it falls back
  to a ``human_review_required`` result so the complaint is *always* persisted
  with a valid result and never destroyed.
* **Persist** — records the run + trace events (``agent_runs`` /
  ``agent_events``), advances the complaint to ``PRIORITIZED`` on success and
  appends a timeline entry.

Provider failures (timeout / rate limit / connection / config) mark the run
``FAILED`` and leave the complaint intact so the caller can retry — Groq is
never called directly from the UI, only through this service.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.models import AgentRun, Complaint
from app.models.enums import AgentStatus, ComplaintStatus, TriageSeverity, TriageUrgency
from app.schemas.triage import TriageInput, TriageOutput
from app.services import agent_run_service
from app.services.ai_governance_service import PROMPT_VERSION_TRIAGE, log_ai_decision
from app.services.ai_service import AIError, AIService, AIStructuredParsingError, get_ai_service
from app.services.audit_service import ACTION_COMPLAINT_TRIAGE, record_audit
from app.services.classification_service import _rules_category
from app.services.complaint_service import record_status_transition
from app.services.evidence_validation_service import validate_category_claim

logger = logging.getLogger(__name__)

AGENT_NAME = "triage"

# The retry budget for malformed / invalid model output. After this many
# consecutive failures to produce a valid TriageOutput the agent gives up and
# routes the complaint to human review rather than persisting bad data.
DEFAULT_MAX_VALIDATION_RETRIES = 3

# Fallback result used when the model cannot produce a valid TriageOutput even
# after retrying. It stays schema-valid and flags the complaint for a human.
_FALLBACK = TriageOutput(
    category="OTHER",
    severity=TriageSeverity.MEDIUM,
    urgency=TriageUrgency.MEDIUM,
    infrastructure_type="unclassified",
    summary="Unable to classify automatically; manual review required.",
    confidence=0.0,
    recommended_action="Refer this complaint to a human reviewer for triage.",
    human_review_required=True,
)


class TriageState(TypedDict, total=False):
    """Graph state for the triage agent.

    Carries the input, the current best-validated output, the retry bookkeeping,
    and the live SQLAlchemy session / AI service used by the persist node.
    """

    input: TriageInput
    output: TriageOutput | None
    attempt: int
    max_retries: int
    human_review: bool
    parse_error: bool  # True when the last triage call was un-parseable
    fatal_error: bool  # True when the last triage call was a provider failure
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
# Graph nodes
# --------------------------------------------------------------------------- #
async def _triage_node(state: TriageState) -> dict[str, Any]:
    """Call Groq for a structured triage result, or record the failure reason."""
    attempt = state.get("attempt", 0) + 1
    input_data: TriageInput = state["input"]
    ai: AIService = state["ai"]
    run: AgentRun = state["run"]

    await agent_run_service._append_event(state["db"], run, "triage.started", {"attempt": attempt})
    messages = _build_messages(input_data)
    try:
        output: TriageOutput = await ai.structured_completion(messages, TriageOutput)
        return {
            "output": output,
            "attempt": attempt,
            "parse_error": False,
            "fatal_error": False,
            "error": None,
            "human_review": bool(output.human_review_required),
        }
    except AIStructuredParsingError as exc:
        logger.warning("Triage output invalid (attempt %s): %s", attempt, exc)
        return {
            "output": None,
            "attempt": attempt,
            "parse_error": True,
            "fatal_error": False,
            "error": str(exc),
            "human_review": False,
        }
    except AIError as exc:  # provider failure: timeout / rate limit / config / api
        logger.error("Triage provider failure (attempt %s): %s", attempt, exc)
        return {
            "output": None,
            "attempt": attempt,
            "parse_error": False,
            "fatal_error": True,
            "error": str(exc),
            "human_review": False,
        }


def _validate_node(state: TriageState) -> dict[str, Any]:
    """Report the routing decision after a triage attempt."""
    events: list[tuple[str, dict | None]] = state.get("event_log", [])

    if state.get("fatal_error"):
        events.append(("validate.provider_failed", {"error": state.get("error")}))
        return {"event_log": events, "route": "fail"}

    if state.get("output") is None and state.get("parse_error"):
        if state.get("attempt", 0) < state.get("max_retries", DEFAULT_MAX_VALIDATION_RETRIES):
            events.append(("validate.retrying", {"attempt": state.get("attempt")}))
            return {"event_log": events, "route": "retry"}
        # Retry budget exhausted: fall back to human review with a valid result.
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

    # Valid output (possibly flagged for human review by the model).
    if state.get("human_review"):
        events.append(("validate.human_review", {"attempt": state.get("attempt")}))
    else:
        events.append(
            (
                "validate.passed",
                {"attempt": state.get("attempt"), "confidence": _conf(state.get("output"))},
            )
        )
    return {"event_log": events, "route": "persist"}


async def _persist_node(state: TriageState) -> dict[str, Any]:
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
        result=state.get("output"),
        error=state.get("error") if failed else None,
        duration_ms=state.get("duration_ms"),
        events=events,
    )
    # On success advance the complaint to PRIORITIZED. On failure we leave the
    # complaint where it is (AI_ANALYZING) so nothing is destroyed and the
    # caller can retry analysis.
    if not failed:
        await _transition_complaint(
            db,
            state["complaint_id"],
            ComplaintStatus.PRIORITIZED,
            note="AI triage completed.",
        )
    return {}


def _should_route_to(state: TriageState) -> str:
    """Graph router: ''triage'' (retry), ''persist'' (done/fail), ''fail''."""
    return state.get("route", "persist")


# --------------------------------------------------------------------------- #
# Graph building
# --------------------------------------------------------------------------- #
def build_graph() -> Any:
    """Build the ``START → Triage → Validate → Persist → END`` LangGraph state graph."""
    graph = StateGraph(TriageState)
    graph.add_node("triage", _triage_node)
    graph.add_node("validate", _validate_node)
    graph.add_node("persist", _persist_node)

    graph.add_edge(START, "triage")
    graph.add_edge("triage", "validate")
    graph.add_conditional_edges(
        "validate",
        _should_route_to,
        {"triage": "triage", "persist": "persist", "fail": "persist", "retry": "triage"},
    )
    graph.add_edge("persist", END)
    return graph.compile()


# --------------------------------------------------------------------------- #
# Public runner
# --------------------------------------------------------------------------- #
class TriageAgent:
    """Orchestrator that runs the triage LangGraph against a complaint."""

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

    async def run(
        self,
        db: AsyncSession,
        *,
        complaint_id: uuid.UUID,
        input_data: TriageInput,
    ) -> AgentRun:
        """Create a run, execute the graph end-to-end, and return the persisted run."""
        started = time.monotonic()
        run = await agent_run_service.create_run(
            db,
            complaint_id=complaint_id,
            agent=AGENT_NAME,
            model=self._settings.GROQ_MODEL or None,
        )
        await agent_run_service._append_event(db, run, "run.started", {"agent": AGENT_NAME})
        await db.commit()
        run_id = run.id

        state: TriageState = {
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
            "model": self._settings.GROQ_MODEL,
            "complaint_id": complaint_id,
            "duration_ms": None,
            "event_log": [],
        }
        await self._graph.ainvoke(state)

        await self._log_governance(db, input_data, state, complaint_id)
        duration = int((time.monotonic() - started) * 1000)
        reloaded = await agent_run_service.get_run_with_events(db, run_id)
        if reloaded is not None and reloaded.duration_ms is None:
            reloaded.duration_ms = duration
            await db.commit()
        return reloaded or run

    async def _log_governance(
        self,
        db: AsyncSession,
        input_data: TriageInput,
        state: TriageState,
        complaint_id: uuid.UUID,
    ) -> None:
        """Part 28 — persist the AI decision log + evidence cross-check + audit."""
        output: TriageOutput | None = state.get("output")
        if output is None or state.get("fatal_error"):
            return

        decision = await log_ai_decision(
            db,
            complaint_id=complaint_id,
            agent_name=AGENT_NAME,
            model_name=self._settings.GROQ_MODEL or "unconfigured",
            prompt_version=PROMPT_VERSION_TRIAGE,
            input_summary=(input_data.description or "")[:500] or None,
            output_summary=output.summary,
            confidence=output.confidence,
            result=output.model_dump(mode="json"),
            duration_ms=state.get("duration_ms"),
        )
        await record_audit(
            db,
            actor_id=None,
            action=ACTION_COMPLAINT_TRIAGE,
            entity_type="complaint",
            entity_id=str(complaint_id),
            after={
                "category": output.category.value,
                "severity": output.severity.value,
                "human_review": bool(state.get("human_review")),
            },
        )
        # Evidence cross-check: AI category vs deterministic rules category.
        actual_category, _ = _rules_category(input_data.description or "")
        await validate_category_claim(
            db,
            complaint_id=complaint_id,
            decision_id=decision.id,
            claimed_category=output.category.value,
            actual_category=actual_category,
        )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _build_messages(input_data: TriageInput) -> list[dict[str, str]]:
    location = input_data.location or "not specified"
    return [
        {
            "role": "system",
            "content": (
                "You are a municipal civic-complaint triage assistant. Given a citizen's "
                "complaint you must classify it into road / water / garbage / flooding or "
                "another civic category, assess its severity and urgency, identify the "
                "affected infrastructure, and suggest an action. Respond only with valid "
                "JSON matching the requested schema. Use short, factual language."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Complaint in language '{input_data.language}':\n"
                f"Description: {input_data.description}\n"
                f"Reported category: {input_data.category.value}\n"
                f"Location: {location}"
            ),
        },
    ]


def _conf(output: TriageOutput | None) -> float | None:
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
        logger.warning("Triage persist: complaint %s no longer exists", complaint_id)
        return
    if complaint.status == new_status:
        return
    complaint.status = new_status
    db.add(record_status_transition(complaint, new_status, actor_id=None, note=note))
