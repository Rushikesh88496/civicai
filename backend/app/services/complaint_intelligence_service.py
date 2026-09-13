"""Automatic Intelligence Pipeline for complaint detail views (INTELLIGENCE PIPELINE).

Closes the gap between the context-enrichment agent (Part 11) and the
deterministic priority engine (Part 12): nothing triggered them automatically, so
an officer reviewing a complaint had to click "Understand the situation" and then
"Score priority" by hand — and, without a triage run, the score's severity input
stayed at the MEDIUM default and the complaint's own words never counted.

This service makes the pipeline automatic and idempotent on every detail view:

    GET detail → (operational role + flag checked) → check context run
    → run context enrichment if missing/FAILED (persists to ``agent_runs``)
    → check priority run → run deterministic priority if missing/FAILED OR when
    a newer validated upstream signal (triage severity or context) arrived
    after the last score (persists to ``agent_runs`` + ``complaint_priority_history``)
    → the caller returns the detail, so the officer immediately sees the result.

Rules:

* **Roles** — only OFFICER / ADMIN / WARD_REPRESENTATIVE trigger the pipeline;
  citizens viewing their own complaint never pay for (or see) operational runs.
* **Governance flag** — ``COMPLAINTS_AUTO_INTELLIGENCE`` (default True) is a
  hard off-switch; the test suite forces it False so its hundreds of detail
  reads never cross external weather/geocoding services.
* **Idempotency** — a SUCCEEDED run is never replaced by a plain re-view; only
  missing or FAILED runs are (re)run. Manual "Re-run / Re-score" buttons still
  trigger explicit runs and remain the full-retry path.
* **Freshness** — the priority score always reflects the newest validated
  upstream signal, so content (triage severity) and situation (context) changes
  are picked up automatically instead of freezing the score at first view.
* **Fault tolerance** — a failure in either stage is logged and never bubbles to
  the detail response; the officer still sees the complaint, and the FAILED
  status (plus the manual buttons) surfaces the retry affordance.

Every stage reuses the existing access enforcement of the underlying services
(``_assert_can_view`` / ``user_can_view``), so this module never trusts a
client-supplied complaint id.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import User
from app.models.enums import RoleName
from app.services import agent_run_service

logger = logging.getLogger(__name__)

AGENT_CONTEXT = "context"
AGENT_TRIAGE = "triage"
AGENT_PRIORITY = "priority"

# Staff roles whose detail views trigger the automatic intelligence pipeline.
_OPERATIONAL_ROLES = frozenset(
    {
        RoleName.OFFICER.value,
        RoleName.ADMIN.value,
        RoleName.WARD_REPRESENTATIVE.value,
    }
)


async def ensure_intelligence_pipeline(
    db: AsyncSession,
    user: User,
    complaint_id: uuid.UUID,
) -> dict[str, str | None]:
    """Auto-enrich + auto-score ``complaint_id`` if any part is missing or stale.

    Only acts for operational staff while ``COMPLAINTS_AUTO_INTELLIGENCE`` is
    enabled. Every stage persists through the existing service facades, so the
    results survive refresh / re-open / backend restart and feed the existing
    ``*-result`` / ``priority-history`` endpoints the UI reads.

    :returns: per-stage outcome summary (``context`` / ``priority`` →
        ``"ran"`` | ``"skipped"`` | ``"failed"``), for logging and tests.
    """
    settings = get_settings()
    outcome: dict[str, str | None] = {"context": None, "priority": None}

    if not settings.COMPLAINTS_AUTO_INTELLIGENCE:
        return outcome
    if user.role is None or user.role.name not in _OPERATIONAL_ROLES:
        return outcome

    from app.services import context_service, priority_service

    # --- Context enrichment: run when never run, or the last run failed. ------
    ctx_run = await agent_run_service.get_latest_run_for_agent(db, complaint_id, AGENT_CONTEXT)
    if ctx_run is None or ctx_run.status.value == "FAILED":
        outcome["context"] = "ran"
        try:
            await context_service.run_context(db, user, complaint_id)
        except Exception as exc:  # noqa: BLE001 - auto-run must never break a read
            outcome["context"] = "failed"
            logger.warning("Auto-context enrichment failed for %s: %s", complaint_id, exc)

    # --- Priority: run when never run / failed, or when a newer validated -----
    # --- upstream signal (triage severity or context) arrived since scoring. ---
    prio_run = await agent_run_service.get_latest_run_for_agent(db, complaint_id, AGENT_PRIORITY)
    stale = prio_run is None or prio_run.status.value == "FAILED"
    if not stale and prio_run.ended_at is not None:
        newest_upstream: object | None = None
        for up_agent in (AGENT_TRIAGE, AGENT_CONTEXT):
            up_run = await agent_run_service.get_latest_run_for_agent(db, complaint_id, up_agent)
            if up_run is not None and up_run.status.value == "SUCCEEDED" and up_run.ended_at:
                if newest_upstream is None or up_run.ended_at > newest_upstream:
                    newest_upstream = up_run.ended_at
        if newest_upstream is not None and newest_upstream > prio_run.ended_at:
            stale = True

    if stale:
        outcome["priority"] = "ran"
        try:
            await priority_service.run_priority(db, user, complaint_id)
        except Exception as exc:  # noqa: BLE001 - auto-run must never break a read
            outcome["priority"] = "failed"
            logger.warning("Auto-priority scoring failed for %s: %s", complaint_id, exc)

    return outcome
