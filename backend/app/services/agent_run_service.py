"""Persistence helpers for agent runs and trace events (Part 7).

Keeps the DB writes for ``agent_runs`` / ``agent_events`` in one place so the
triage agent and its API wrapper share identical serialization and don't
duplicate commit logic.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.realtime import publish_command_center_refresh
from app.models import AgentEvent, AgentRun
from app.models.enums import AgentStatus
from app.schemas.triage import AgentEventOut, AgentRunOut, TriageOutput


def _result_to_dict(result: BaseModel | dict | None) -> dict | None:
    """Normalize a structured result (Pydantic model or raw dict) to JSON."""
    if result is None:
        return None
    if isinstance(result, BaseModel):
        return result.model_dump(mode="json")
    return dict(result)


async def create_run(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID,
    agent: str,
    model: str | None,
    structured_result: BaseModel | dict | None = None,
    error: str | None = None,
    status: AgentStatus = AgentStatus.RUNNING,
    duration_ms: int | None = None,
) -> AgentRun:
    """Create and commit a new agent run row."""
    run = AgentRun(
        complaint_id=complaint_id,
        agent=agent,
        model=model,
        status=status,
        structured_result=_result_to_dict(structured_result),
        error=error,
        duration_ms=duration_ms,
    )
    db.add(run)
    await db.flush()
    return run


async def _append_event(
    db: AsyncSession, run: AgentRun, event: str, payload: dict | None = None
) -> None:
    db.add(AgentEvent(run_id=run.id, event=event, payload=payload))


async def finalize_run(
    db: AsyncSession,
    run: AgentRun,
    *,
    status: AgentStatus,
    result: BaseModel | dict | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    events: list[tuple[str, dict | None]] | None = None,
) -> AgentRun:
    """Mark a run as succeeded/failed, storing duration, result/error, and any
    trailing trace events, then commit."""
    run.status = status
    run.duration_ms = duration_ms
    run.structured_result = _result_to_dict(result)
    run.error = error
    run.ended_at = datetime.now(UTC)
    for evt, payload in events or []:
        await _append_event(db, run, evt, payload)
    await db.commit()
    # Notify command-center WebSocket clients that activity changed (best-effort).
    await publish_command_center_refresh()
    return run


async def reap_stale_runs(
    db: AsyncSession,
    *,
    complaint_id: uuid.UUID | None = None,
    agent: str | None = None,
    stale_seconds: int = 300,
) -> int:
    """Mark RUNNING agent runs older than ``stale_seconds`` as FAILED.

    A process crash / restart can leave an ``agent_runs`` row stuck in RUNNING
    forever. Without a sweep the result endpoints would report an eternal
    in-progress state (the UI's "Computing…" spinner never resolves) and the
    auto-intelligence pipeline would treat the row as fresh — never re-running
    the interrupted stage. This idempotent sweep flips stale rows to FAILED so
    callers surface an honest error and retry. Returns the number of runs
    reclaimed.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=max(1, int(stale_seconds)))
    stmt = select(AgentRun).where(
        AgentRun.status == AgentStatus.RUNNING,
        AgentRun.started_at < cutoff,
    )
    if complaint_id is not None:
        stmt = stmt.where(AgentRun.complaint_id == complaint_id)
    if agent is not None:
        stmt = stmt.where(AgentRun.agent == agent)
    rows = (await db.execute(stmt)).scalars().all()
    if not rows:
        return 0
    now = datetime.now(UTC)
    for run in rows:
        run.status = AgentStatus.FAILED
        run.error = "Run marked failed — interrupted or stale RUNNING."
        run.ended_at = now
    await db.commit()
    return len(rows)


async def get_latest_run(db: AsyncSession, complaint_id: uuid.UUID) -> AgentRun | None:
    """Return the most recent agent run for a complaint (any agent)."""
    return await db.scalar(
        select(AgentRun)
        .where(AgentRun.complaint_id == complaint_id)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )


async def get_latest_run_for_agent(
    db: AsyncSession, complaint_id: uuid.UUID, agent: str
) -> AgentRun | None:
    """Return the most recent run of a *specific* agent for a complaint.

    Unlike :func:`get_latest_run` (which returns the newest run regardless of
    agent), this scopes to one agent so a downstream agent (e.g. the Part 13
    routing agent) can read the latest triage / vision / priority / context
    output independently.
    """
    return await db.scalar(
        select(AgentRun)
        .where(AgentRun.complaint_id == complaint_id, AgentRun.agent == agent)
        .order_by(AgentRun.started_at.desc())
        .limit(1)
    )


async def get_run_with_events(db: AsyncSession, run_id: uuid.UUID) -> AgentRun | None:
    return await db.scalar(
        select(AgentRun).where(AgentRun.id == run_id).options(selectinload(AgentRun.events))
    )


def run_out(run: AgentRun) -> AgentRunOut:
    """Serialize an AgentRun model to its response schema."""
    result: TriageOutput | None = None
    if run.structured_result is not None:
        result = TriageOutput.model_validate(run.structured_result)
    return AgentRunOut(
        id=run.id,
        complaint_id=run.complaint_id,
        agent=run.agent,
        model=run.model,
        status=run.status,
        duration_ms=run.duration_ms,
        structured_result=result,
        error=run.error,
        started_at=run.started_at,
        ended_at=run.ended_at,
    )


def event_out(event: AgentEvent) -> AgentEventOut:
    return AgentEventOut(
        id=event.id,
        run_id=event.run_id,
        event=event.event,
        payload=event.payload,
        recorded_at=event.recorded_at,
    )
