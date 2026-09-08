import enum


class RoleName(enum.StrEnum):
    CITIZEN = "CITIZEN"
    OFFICER = "OFFICER"
    WARD_REPRESENTATIVE = "WARD_REPRESENTATIVE"
    FIELD_WORKER = "FIELD_WORKER"
    ADMIN = "ADMIN"
    # Privileged management role that gates the Super-Admin Panel (Part 27).
    SUPER_ADMIN = "SUPER_ADMIN"


class WorkerStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ON_LEAVE = "ON_LEAVE"


class RepresentativeStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"


class ComplaintCategory(enum.StrEnum):
    ROAD = "ROAD"
    SANITATION = "SANITATION"
    WATER = "WATER"
    ELECTRICITY = "ELECTRICITY"
    PUBLIC_SAFETY = "PUBLIC_SAFETY"
    PARKS = "PARKS"
    STREET_LIGHTING = "STREET_LIGHTING"
    OTHER = "OTHER"
    # Added for the multimodal complaint submission flow (Part 4).
    WATER_LEAK = "WATER_LEAK"
    FLOODING = "FLOODING"
    GARBAGE = "GARBAGE"
    DRAINAGE = "DRAINAGE"
    FALLEN_TREE = "FALLEN_TREE"


class MediaType(enum.StrEnum):
    IMAGE = "IMAGE"
    VIDEO = "VIDEO"


class AgentStatus(enum.StrEnum):
    """Lifecycle of a single agent run (Part 7)."""

    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class TriageSeverity(enum.StrEnum):
    """Impact severity assigned by the triage agent (Part 7)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class TriageUrgency(enum.StrEnum):
    """How quickly the issue should be actioned (Part 7)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ComplaintPriority(enum.StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ComplaintStatus(enum.StrEnum):
    # Legacy statuses (kept for backward compatibility with existing data).
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    # Lifecycle timeline statuses (Part 5). New complaints start at SUBMITTED
    # and every change is recorded in complaint_status_history.
    SUBMITTED = "SUBMITTED"
    AI_ANALYZING = "AI_ANALYZING"
    EVIDENCE_VERIFIED = "EVIDENCE_VERIFIED"
    WARD_IDENTIFIED = "WARD_IDENTIFIED"
    PRIORITIZED = "PRIORITIZED"
    DEPARTMENT_ASSIGNED = "DEPARTMENT_ASSIGNED"
    WORK_ORDER_CREATED = "WORK_ORDER_CREATED"
    WORKER_ASSIGNED = "WORKER_ASSIGNED"
    CITIZEN_VERIFIED = "CITIZEN_VERIFIED"
    CLOSED = "CLOSED"


class CorrelationStatus(enum.StrEnum):
    """Duplicate-detection outcome for a complaint (Part 9).

    * ``NEW_INCIDENT`` — no strong match to an existing complaint (or none run yet).
    * ``POSSIBLE_DUPLICATE`` — the correlation agent found a likely match; a human
      officer must decide.
    * ``CONFIRMED_DUPLICATE`` — an authorized officer confirmed it is a duplicate
      of another complaint.
    """

    NEW_INCIDENT = "NEW_INCIDENT"
    POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"
    CONFIRMED_DUPLICATE = "CONFIRMED_DUPLICATE"


class CorrelationMatchStatus(enum.StrEnum):
    """Lifecycle of a single candidate duplicate pair (Part 9).

    The correlation agent creates ``PENDING`` candidate links. An authorized
    officer either ``CONFIRMED`` (they agree it is a duplicate) or ``REJECTED``
    (false positive).
    """

    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class DynamicPriority(enum.StrEnum):
    """Deterministic priority bucket assigned by the Priority Engine (Part 12).

    Derived purely from the weighted score (P1 = highest). These are explicitly
    distinct from ``ComplaintPriority`` (the triage agent's severity label) so a
    deterministic numeric score can never be conflated with an LLM suggestion.
    """

    P1_CRITICAL = "P1_CRITICAL"
    P2_HIGH = "P2_HIGH"
    P3_MEDIUM = "P3_MEDIUM"
    P4_LOW = "P4_LOW"


class WorkOrderStatus(enum.StrEnum):
    """Lifecycle of a work order (Part 14).

    A dispatched work order starts as ``PENDING_APPROVAL``; the Dispatch Agent
    produces a draft with a recommended worker and ETA, and an authorized officer
    ``APPROVES`` it (creating the explicit worker assignment) or ``REJECTS`` it
    with a reason. Once approved/assigned it can be ``ASSIGNED`` / ``REASSIGNED``,
    move to ``IN_PROGRESS``, ``ESCALATED`` (no worker / out of SLA), ``COMPLETED``
    and finally ``CLOSED``.
    """

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ESCALATED = "ESCALATED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class AssignmentStatus(enum.StrEnum):
    """Lifecycle of a single worker/work-order assignment (Part 14).

    ``ASSIGNED`` on initial assignment, ``REASSIGNED`` when an officer moves the
    order to another worker, and ``UNASSIGNED`` when the previous holder loses the
    order (only one assignment is active per work order at a time).
    """

    ASSIGNED = "ASSIGNED"
    REASSIGNED = "REASSIGNED"
    UNASSIGNED = "UNASSIGNED"


class WorkOrderAction(enum.StrEnum):
    """The officer actions recorded as a work-order status-history audit trail."""

    APPROVE = "APPROVE"
    ASSIGN = "ASSIGN"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"
    REJECT = "REJECT"
    CLOSE = "CLOSE"
    DISPATCH = "DISPATCH"
    # Field worker workflow actions (Part 18).
    ACCEPT = "ACCEPT"
    START_WORK = "START_WORK"
    COMPLETE_WORK = "COMPLETE_WORK"
    CHECK_IN = "CHECK_IN"
    PHOTO_BEFORE = "PHOTO_BEFORE"
    PHOTO_AFTER = "PHOTO_AFTER"
    NOTE_ADDED = "NOTE_ADDED"
    # Human review action (Part 19): a failed AI repair verification is sent
    # back to the field worker for follow-up.
    REOPEN = "REOPEN"


class DepartmentCode(enum.StrEnum):
    """The seven departments the Routing Agent (Part 13) can assign a complaint to.

    These are the fixed routing targets requested for the department routing agent
    (Water, Roads, Electrical, Waste, Drainage, Parks, Emergency/Disaster). They are
    intentionally distinct from the seeded ``Department`` DB table (which holds
    legacy operational names) — routing decisions are deterministic and reference
    these codes.
    """

    WATER = "WATER"
    ROADS = "ROADS"
    ELECTRICAL = "ELECTRICAL"
    WASTE = "WASTE"
    DRAINAGE = "DRAINAGE"
    PARKS = "PARKS"
    EMERGENCY_DISASTER = "EMERGENCY_DISASTER"


# Human-friendly display labels for the DepartmentCode routing targets.
DEPARTMENT_LABELS: dict[str, str] = {
    DepartmentCode.WATER.value: "Water",
    DepartmentCode.ROADS.value: "Roads",
    DepartmentCode.ELECTRICAL.value: "Electrical",
    DepartmentCode.WASTE.value: "Waste",
    DepartmentCode.DRAINAGE.value: "Drainage",
    DepartmentCode.PARKS.value: "Parks",
    DepartmentCode.EMERGENCY_DISASTER.value: "Emergency / Disaster",
}


class CriticalLocationCategory(enum.StrEnum):
    """Kind of critical infrastructure tracked for nearby-place lookups (Part 10).

    The GIS service groups these under the "critical infrastructure" and
    "nearby places" facility categories requested for spatial intelligence.
    """

    HOSPITAL = "HOSPITAL"
    SCHOOL = "SCHOOL"
    BUS_STOP = "BUS_STOP"
    POLICE_STATION = "POLICE_STATION"
    FIRE_STATION = "FIRE_STATION"
    ROAD = "ROAD"
    TRANSPORT = "TRANSPORT"
    OTHER = "OTHER"


# Ordered lifecycle for the Complaint Tracking timeline. The legacy statuses
# OPEN and ESCALATED are not part of the primary linear pipeline; OPEN maps to
# the start (a submitted-but-not-yet-processed complaint) and ESCALATED is a
# terminal escalation branch.
STATUS_PIPELINE: list[str] = [
    ComplaintStatus.SUBMITTED.value,
    ComplaintStatus.AI_ANALYZING.value,
    ComplaintStatus.EVIDENCE_VERIFIED.value,
    ComplaintStatus.WARD_IDENTIFIED.value,
    ComplaintStatus.PRIORITIZED.value,
    ComplaintStatus.DEPARTMENT_ASSIGNED.value,
    ComplaintStatus.WORK_ORDER_CREATED.value,
    ComplaintStatus.WORKER_ASSIGNED.value,
    ComplaintStatus.IN_PROGRESS.value,
    ComplaintStatus.RESOLVED.value,
    ComplaintStatus.CITIZEN_VERIFIED.value,
    ComplaintStatus.CLOSED.value,
]


class VerificationStatus(enum.StrEnum):
    """AI repair-verification outcome for a completed work order (Part 19).

    The Resolution-Verification agent compares the complaint description and the
    worker's BEFORE / AFTER photos:

    * ``VERIFIED`` — the AFTER photo shows the reported issue is fixed.
    * ``PARTIALLY_RESOLVED`` — visibly improved but not fully fixed.
    * ``NOT_RESOLVED`` — the AFTER photo still shows (or shows no change to) the
      reported issue.
    * ``NEEDS_HUMAN_REVIEW`` — the AI could not decide confidently (low
      confidence / malformed output / critical priority), or a human sign-off is
      mandated by policy.

    Only AI results that pass the configured confidence / safety gates are
    persisted; every non-``VERIFIED`` outcome (and every critical-priority one)
    requires an authorized human to act before the complaint can close.
    """

    VERIFIED = "VERIFIED"
    PARTIALLY_RESOLVED = "PARTIALLY_RESOLVED"
    NOT_RESOLVED = "NOT_RESOLVED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"


class SlaState(enum.StrEnum):
    """SLA health of an open work order (Part 20).

    Computed by the SLA Monitoring agent from the order's configurable deadline
    (see ``sla_policies``) and remaining time:

    * ``ON_TRACK`` — deadline far enough away (elapsed <= at-risk threshold).
    * ``AT_RISK`` — warning window entered; the order needs attention soon.
    * ``BREACHED`` — deadline passed; the order is past its SLA.
    * ``COMPLETED`` — the work order was finished (SLA no longer applies).
    """

    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"
    COMPLETED = "COMPLETED"


class VerificationReviewDecision(enum.StrEnum):
    """The decision an authorized human makes when reviewing a verification.

    * ``CONFIRM_VERIFIED`` — the reviewer accepts that the repair is complete;
      the verification is certified and moves on.
    * ``REQUIRES_FOLLOWUP`` — the reviewer rejects the outcome; the work order is
      reopened (COMPLETED → IN_PROGRESS) so the field worker can return.
    """

    CONFIRM_VERIFIED = "CONFIRM_VERIFIED"
    REQUIRES_FOLLOWUP = "REQUIRES_FOLLOWUP"


class InfrastructureCategory(enum.StrEnum):
    """Kind of municipal infrastructure asset tracked for maintenance (Part 24).

    These map onto the seven routing ``DepartmentCode`` targets so a preventive
    work order for an asset can reference the department that owns it.
    """

    ROAD = "ROAD"
    BRIDGE = "BRIDGE"
    WATER_MAIN = "WATER_MAIN"
    SEWER = "SEWER"
    DRAINAGE = "DRAINAGE"
    STREET_LIGHTING = "STREET_LIGHTING"
    PARK = "PARK"
    PUBLIC_BUILDING = "PUBLIC_BUILDING"


class InfrastructureRiskLevel(enum.StrEnum):
    """Predicted-maintenance-risk bucket for an infrastructure asset (Part 24).

    Derived deterministically from the model's ``failure_probability`` using the
    configured thresholds (``<0.25`` LOW, ``<0.50`` MEDIUM, ``<0.75`` HIGH, at
    least ``0.75`` CRITICAL). It is a *predicted risk*, never a claim that an
    asset will fail.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PredictionReviewStatus(enum.StrEnum):
    """Human review state of a stored infrastructure-risk prediction (Part 24).

    The officer workflow: the model produces a predicted risk → an authorized
    officer reviews it (``APPROVED`` or ``REJECTED``) → on approval an optional
    preventive work order may be created. ``PENDING`` means nobody has decided.
    """

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class KnowledgeCategory(enum.StrEnum):
    """Section of the civic knowledge base used by the Citizen AI Assistant (Part 25).

    Documents are organized by category so retrieval stays explainable and the
    assistant can surface a source reference for every policy-based answer. The
    categories mirror the assistant's answerable topics: SLA policy, department
    responsibilities, complaint categories, citizen FAQs and municipal procedures.
    """

    SLA_POLICY = "SLA_POLICY"
    DEPARTMENT_RESPONSIBILITY = "DEPARTMENT_RESPONSIBILITY"
    COMPLAINT_CATEGORY = "COMPLAINT_CATEGORY"
    CITIZEN_FAQ = "CITIZEN_FAQ"
    MUNICIPAL_PROCEDURE = "MUNICIPAL_PROCEDURE"


class PreventiveWorkOrderStatus(enum.StrEnum):
    """Lifecycle of a preventive infrastructure work order (Part 24).

    An officer creates a draft (``PENDING_APPROVAL``) from an *approved*
    prediction and then approves / rejects / completes / cancels it. Distinct
    from the complaint-driven ``WorkOrderStatus`` because no complaint exists
    yet — this is proactive maintenance on a predicted-at-risk asset.
    """

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LanguageCode(enum.StrEnum):
    """Supported language codes for the multilingual civic AI (Part 26).

    The deterministic language pipeline uses these three ISO 639-1 codes.
    An ``en`` default is applied whenever detection fails or is skipped.
    """

    EN = "en"
    HI = "hi"
    MR = "mr"


# Human-readable labels for supported languages (used by the API and frontend).
SUPPORTED_LANGUAGES: dict[str, str] = {
    LanguageCode.EN.value: "English",
    LanguageCode.HI.value: "Hindi",
    LanguageCode.MR.value: "Marathi",
}
