"""SLA Monitoring Agent (Part 20) — a deterministic LangGraph agent (no LLM).

Runs the ``START -> scan -> escalate -> persist -> END`` graph over all monitored
work orders:

1. **scan** — resolves the most specific ``sla_policies`` rule per order, computes
   each order's state (``ON_TRACK / AT_RISK / BREACHED / COMPLETED``), progress
   and countdown, and backfills a missing ``sla_hours`` / ``due_at`` deadline from
   the resolved rule.
2. **escalate** — compares against the previous ``sla_monitor`` run and raises
   ``SLA_AT_RISK`` / ``SLA_BREACHED`` notifications to staff (OFFICER / ADMIN)
   only on a *transition* into that state, so repeat runs never spam.
3. **persist** — writes the structured ``SlaScanOutput`` to ``agent_runs``
   (agent="sla_monitor") with trace events per bucket.

``now`` is injectable so tests can simulate time (on-time / approaching /
breached / completed) without touching the real clock.
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AgentRun, Role, User
from app.models.enums import AgentStatus, RoleName
from app.schemas.sla import (
    NOTIFICATION_SLA_AT_RISK,
    NOTIFICATION_SLA_BREACHED,
    OrderSlaSnapshot,
    SlaScanOutput,
)
from app.services import agent_run_service, notification_service, sla_service

logger = logging.getLogger(__name__)

AGENT_NAME = "sla_monitor"

# Notification types the escalation step produces (free strings).
_SLA_AT_RISK = NOTIFICATION_SLA_AT_RISK
_SLA_BREACHED = NOTIFICATION_SLA_BREACHED


class SlaMonitorState(TypedDict, total=False):
    db: AsyncSession
    now: datetime
    department: str | None
    priority: str | None
    run: AgentRun
    scan: SlaScanOutput | None
    final_result: SlaScanOutput | None
    fatal_error: bool
    error: str | None
    duration_ms: int | None
    event_log: list[tuple[str, dict | None]]


def _state_str(snapshot: OrderSlaSnapshot) -> str:
    return snapshot.state.value if hasattr(snapshot.state, "value") else snapshot.state


async def _previous_scan(db: AsyncSession) -> SlaScanOutput | None:
    """The orders/states seen by the last completed ``sla_monitor`` run."""
    run = await db.scalar(
        select(AgentRun)
        .where(
            AgentRun.agent == AGENT_NAME,
            AgentRun.status == AgentStatus.SUCCEEDED,
        )
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )
    if run is None or run.structured_result is None:
        return None
    try:
        return SlaScanOutput.model_validate(run.structured_result)
    except Exception:  # noqa: BLE001  (malformed legacy row -> treat as no prior run)
        return None


async def _load_staff(db: AsyncSession) -> list[User]:
    roles = (RoleName.OFFICER.value, RoleName.ADMIN.value)
    rows = (
        (
            await db.execute(
                select(User)
                .join(Role, Role.id == User.role_id)
                .where(Role.name.in_(roles), User.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


async def _notify(
    db: AsyncSession,
    staff: list[User],
    kind: str,
    snap: OrderSlaSnapshot,
) -> None:
    shown = snap.remaining_human or "no deadline set"
    label = "breached" if kind == _SLA_BREACHED else "at risk"
    body = f"SLA {label} for {snap.department} order ({snap.incident or 'untitled'}) — {shown}."
    await notification_service.notify(
        db,
        targets=staff,
        notification_type=kind,
        complaint_id=snap.complaint_id,
        work_order_id=snap.work_order_id,
        body=body,
        link=f"/officer/work-orders/{snap.work_order_id}",
    )


async def _scan_node(state: SlaMonitorState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    await agent_run_service._append_event(db, run, "sla.started", {"now": state["now"].isoformat()})
    await db.flush()

    scan = await sla_service.scan(
        db,
        now=state["now"],
        department=state.get("department"),
        priority=state.get("priority"),
        backfill=True,
    )
    return {"scan": scan, "fatal_error": False, "error": None}


async def _escalate_node(state: SlaMonitorState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    scan: SlaScanOutput = state["scan"]
    prior = await _previous_scan(db)
    prior_states = (
        {s.work_order_id: _state_str(s) for s in prior.orders} if prior is not None else {}
    )
    staff = await _load_staff(db)

    sent: dict[str, int] = {_SLA_AT_RISK: 0, _SLA_BREACHED: 0}
    events: list[tuple[str, dict | None]] = []
    # Breaches first so they are always escalated ahead of warnings.
    ordered = sorted(
        scan.orders,
        key=lambda s: 0 if _state_str(s) == "BREACHED" else 1 if _state_str(s) == "AT_RISK" else 2,
    )
    for snap in ordered:
        state = _state_str(snap)
        prior_state = prior_states.get(snap.work_order_id)

        if state == "BREACHED":
            if prior_state != "BREACHED" and staff:
                await _notify(db, staff, _SLA_BREACHED, snap)
                sent[_SLA_BREACHED] += len(staff)
        elif state == "AT_RISK":
            if prior_state in (None, "ON_TRACK") and staff:
                await _notify(db, staff, _SLA_AT_RISK, snap)
                sent[_SLA_AT_RISK] += len(staff)

        events.append(
            (
                f"sla.{state.lower()}",
                {
                    "work_order_id": str(snap.work_order_id),
                    "complaint_id": str(snap.complaint_id),
                    "remaining_human": snap.remaining_human,
                },
            )
        )

    scan.notifications_sent = sent
    await db.flush()
    return {"final_result": scan, "event_log": events, "fatal_error": False}


async def _persist_node(state: SlaMonitorState) -> dict[str, Any]:
    db: AsyncSession = state["db"]
    run: AgentRun = state["run"]
    scan: SlaScanOutput = state["final_result"]
    events: list[tuple[str, dict | None]] = state.get("event_log", [])
    failed = bool(state.get("fatal_error"))

    if failed:
        events.append(("sla.failed", {"error": state.get("error")}))
        await agent_run_service.finalize_run(
            db,
            run,
            status=AgentStatus.FAILED,
            result=None,
            error=state.get("error"),
            duration_ms=state.get("duration_ms"),
            events=events,
        )
    else:
        await db.flush()
        await agent_run_service.finalize_run(
            db,
            run,
            status=AgentStatus.SUCCEEDED,
            result=scan,
            error=None,
            duration_ms=state.get("duration_ms"),
            events=[
                (
                    "sla.checked",
                    {
                        "counts": scan.counts.model_dump(mode="json"),
                        "notifications_sent": scan.notifications_sent,
                    },
                ),
            ]
            + events,
        )
    return {}


def build_graph() -> Any:
    graph = StateGraph(SlaMonitorState)
    graph.add_node("scan", _scan_node)
    graph.add_node("escalate", _escalate_node)
    graph.add_node("persist", _persist_node)
    graph.add_edge(START, "scan")
    graph.add_edge("scan", "escalate")
    graph.add_edge("escalate", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


class SlaAgent:
    """Orchestrator that runs the deterministic SLA-monitoring graph."""

    def __init__(
        self,
        *,
        graph: Any | None = None,
        now: datetime | None = None,
    ) -> None:
        self._graph = graph if graph is not None else build_graph()
        self._now = now

    async def run(
        self,
        db: AsyncSession,
        *,
        department: str | None = None,
        priority: str | None = None,
    ) -> AgentRun:
        started = time.monotonic()
        now = self._now or datetime.now(UTC)
        run = await agent_run_service.create_run(
            db, complaint_id=None, agent=AGENT_NAME, model=None
        )
        await agent_run_service._append_event(
            db, run, "run.started", {"agent": AGENT_NAME, "now": now.isoformat()}
        )
        await db.commit()

        state: SlaMonitorState = {
            "db": db,
            "now": now,
            "department": department,
            "priority": priority,
            "run": run,
            "scan": None,
            "final_result": None,
            "fatal_error": False,
            "error": None,
            "duration_ms": None,
            "event_log": [],
        }
        try:
            await self._graph.ainvoke(state)
        except Exception as exc:  # noqa: BLE001
            logger.exception("sla_monitor run crashed")
            state["fatal_error"] = True
            state["error"] = str(exc)[:1000]
            await self._graph.ainvoke(state)

        duration = int((time.monotonic() - started) * 1000)
        reloaded = await agent_run_service.get_run_with_events(db, run.id)
        if reloaded is not None and reloaded.duration_ms is None:
            reloaded.duration_ms = duration
            await db.commit()
        return reloaded or run


__all__ = ["AGENT_NAME", "SlaAgent", "build_graph"]
