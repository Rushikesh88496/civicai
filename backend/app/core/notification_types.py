"""Notification event catalog (Part 21).

Central registry of every notification event the system produces, with the
roles that receive it, a default title/delivery channel and a human-readable
label. ``stored_type`` is the value persisted in
``notifications.notification_type``; legacy types produced before Part 21 keep
their original strings so existing consumers (and tests) stay stable.

Canonical event -> stored type mapping:
    RESOLVED   -> WORK_ORDER_COMPLETED  (legacy, produced since Part 18)
    SLA_RISK   -> SLA_AT_RISK           (legacy, produced since Part 20)
    SLA_BREACH -> SLA_BREACHED          (legacy, produced since Part 20)
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# Canonical event keys (typed constants so producers never typo the strings)
# --------------------------------------------------------------------------- #

# Citizens
EVENT_COMPLAINT_RECEIVED = "COMPLAINT_RECEIVED"
EVENT_AI_COMPLETE = "AI_COMPLETE"
EVENT_PRIORITY_ASSIGNED = "PRIORITY_ASSIGNED"
EVENT_WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
EVENT_WORKER_ASSIGNED = "WORKER_ASSIGNED"
EVENT_REPAIR_STARTED = "REPAIR_STARTED"
EVENT_RESOLVED = "RESOLVED"

# Officers / admins
EVENT_P1_ALERT = "P1_ALERT"
EVENT_SLA_RISK = "SLA_RISK"
EVENT_SLA_BREACH = "SLA_BREACH"
EVENT_HUMAN_REVIEW = "HUMAN_REVIEW"

# Field workers
EVENT_NEW_ASSIGNMENT = "NEW_ASSIGNMENT"
EVENT_PRIORITY_CHANGE = "PRIORITY_CHANGE"
EVENT_REASSIGNMENT = "REASSIGNMENT"

# Wards / representatives + cross-role
EVENT_WARD_ALERT = "WARD_ALERT"
EVENT_ESCALATION = "ESCALATION"

# Legacy events (kept for completeness / documentation)
EVENT_MESSAGE = "MESSAGE"
EVENT_WORK_ORDER_REOPENED = "WORK_ORDER_REOPENED"

# All canonical keys, for validation in producers/tests.
ALL_EVENTS: frozenset[str] = frozenset(
    {
        EVENT_COMPLAINT_RECEIVED,
        EVENT_AI_COMPLETE,
        EVENT_PRIORITY_ASSIGNED,
        EVENT_WORK_ORDER_CREATED,
        EVENT_WORKER_ASSIGNED,
        EVENT_REPAIR_STARTED,
        EVENT_RESOLVED,
        EVENT_P1_ALERT,
        EVENT_SLA_RISK,
        EVENT_SLA_BREACH,
        EVENT_HUMAN_REVIEW,
        EVENT_NEW_ASSIGNMENT,
        EVENT_PRIORITY_CHANGE,
        EVENT_REASSIGNMENT,
        EVENT_WARD_ALERT,
        EVENT_ESCALATION,
        EVENT_MESSAGE,
        EVENT_WORK_ORDER_REOPENED,
    }
)

CHANNEL_INBOX = "inbox"
CHANNEL_EMAIL = "email"


@dataclass(frozen=True)
class EventMeta:
    """Metadata for a notification event."""

    stored_type: str
    label: str
    default_title: str | None = None
    channel: str = CHANNEL_INBOX
    # Roles the event is primarily aimed at (informational: used by tests/UI).
    roles: tuple[str, ...] = field(default_factory=tuple)


def _roles(*roles: str) -> tuple[str, ...]:
    return tuple(roles)


_CITIZEN_ROLES = _roles("CITIZEN")
_STAFF_ROLES = _roles("OFFICER", "ADMIN")
_WORKER_ROLES = _roles("FIELD_WORKER")
_REP_ROLES = _roles("WARD_REPRESENTATIVE")


_LEGACY_RESOLVED = "WORK_ORDER_COMPLETED"
_LEGACY_SLA_RISK = "SLA_AT_RISK"
_LEGACY_SLA_BREACH = "SLA_BREACHED"

EVENT_META: dict[str, EventMeta] = {
    EVENT_COMPLAINT_RECEIVED: EventMeta(
        stored_type=EVENT_COMPLAINT_RECEIVED,
        label="Complaint received",
        default_title="Complaint received",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_AI_COMPLETE: EventMeta(
        stored_type=EVENT_AI_COMPLETE,
        label="AI analysis complete",
        default_title="AI analysis complete",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_PRIORITY_ASSIGNED: EventMeta(
        stored_type=EVENT_PRIORITY_ASSIGNED,
        label="Priority assigned",
        default_title="Priority assigned",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_WORK_ORDER_CREATED: EventMeta(
        stored_type=EVENT_WORK_ORDER_CREATED,
        label="Work order created",
        default_title="Work order created",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_WORKER_ASSIGNED: EventMeta(
        stored_type=EVENT_WORKER_ASSIGNED,
        label="Worker assigned",
        default_title="Worker assigned",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_REPAIR_STARTED: EventMeta(
        stored_type=EVENT_REPAIR_STARTED,
        label="Repair started",
        default_title="Repair started",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_RESOLVED: EventMeta(
        stored_type=_LEGACY_RESOLVED,
        label="Complaint resolved",
        default_title="Complaint resolved",
        roles=_CITIZEN_ROLES,
    ),
    EVENT_P1_ALERT: EventMeta(
        stored_type=EVENT_P1_ALERT,
        label="P1 alert",
        default_title="P1 priority alert",
        roles=_STAFF_ROLES,
    ),
    EVENT_SLA_RISK: EventMeta(
        stored_type=_LEGACY_SLA_RISK,
        label="SLA at risk",
        default_title="SLA at risk",
        roles=_STAFF_ROLES,
    ),
    EVENT_SLA_BREACH: EventMeta(
        stored_type=_LEGACY_SLA_BREACH,
        label="SLA breached",
        default_title="SLA breached",
        roles=_STAFF_ROLES,
    ),
    EVENT_HUMAN_REVIEW: EventMeta(
        stored_type=EVENT_HUMAN_REVIEW,
        label="Needs human review",
        default_title="Repair verification needs review",
        roles=_STAFF_ROLES,
    ),
    EVENT_NEW_ASSIGNMENT: EventMeta(
        stored_type=EVENT_NEW_ASSIGNMENT,
        label="New assignment",
        default_title="New job assigned to you",
        roles=_WORKER_ROLES,
    ),
    EVENT_PRIORITY_CHANGE: EventMeta(
        stored_type=EVENT_PRIORITY_CHANGE,
        label="Priority changed",
        default_title="Job priority changed",
        roles=_WORKER_ROLES,
    ),
    EVENT_REASSIGNMENT: EventMeta(
        stored_type=EVENT_REASSIGNMENT,
        label="Reassignment",
        default_title="Job reassigned to you",
        roles=_WORKER_ROLES,
    ),
    EVENT_WARD_ALERT: EventMeta(
        stored_type=EVENT_WARD_ALERT,
        label="Ward alert",
        default_title="New issue in your ward",
        roles=_REP_ROLES,
    ),
    EVENT_ESCALATION: EventMeta(
        stored_type=EVENT_ESCALATION,
        label="Escalation",
        default_title="Complaint escalated",
        roles=_REP_ROLES,
    ),
    EVENT_MESSAGE: EventMeta(
        stored_type=EVENT_MESSAGE,
        label="New message",
        default_title="New message",
        channel=CHANNEL_INBOX,
    ),
    EVENT_WORK_ORDER_REOPENED: EventMeta(
        stored_type=EVENT_WORK_ORDER_REOPENED,
        label="Work order reopened",
        default_title="Work order reopened",
    ),
}


def meta_for(event: str) -> EventMeta:
    """Return the metadata for a canonical event (raises on unknown keys)."""
    try:
        return EVENT_META[event]
    except KeyError:
        raise ValueError(f"Unknown notification event: {event!r}") from None


def stored_type_for(event: str) -> str:
    """Resolve the canonical event to the persisted notification_type string."""
    return meta_for(event).stored_type


def default_title_for(event: str) -> str | None:
    return meta_for(event).default_title
