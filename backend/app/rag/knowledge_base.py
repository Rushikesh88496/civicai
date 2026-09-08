"""Civic knowledge base for the Citizen AI Assistant (Part 25).

Holds the citable, official-language document set the assistant retrieves from
(``KNOWLEDGE_DOCUMENTS``) and the idempotent seeding routine
(:func:`ensure_knowledge_base`) that upserts them with pgvector embeddings.

Every document is small and self-contained; the retrieval stage returns the
top-k nearest documents and the assistant answers *only* from that context,
attaching a ``source`` reference for each document it used. All policy facts
below intentionally mirror the domain's real system semantics (priority buckets
P1..P4 with thresholds 80/60/40, SLA deadlines 24/48/72/168 h, the seven routing
departments and the complaint lifecycle statuses).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import KnowledgeDocument
from app.models.enums import KnowledgeCategory
from app.services.embedding_service import EmbeddingService

# --------------------------------------------------------------------------- #
# Source documents (title, section, category, source_ref, content)
# --------------------------------------------------------------------------- #
KNOWLEDGE_DOCUMENTS: list[dict] = [
    # ---- SLA policy ------------------------------------------------------- #
    {
        "title": "SLA response times by priority",
        "section": "SLA - Response Times",
        "category": KnowledgeCategory.SLA_POLICY,
        "source_ref": "Citizen Charter, §Response Times (v2, 2026)",
        "content": (
            "The municipal SLA sets how quickly a complaint is answered once a work "
            "order is approved. P1 (critical) complaints must be addressed within 24 "
            "hours, P2 within 48 hours, P3 within 72 hours and P4 within 168 hours. "
            "Only approved work orders count against the clock; a lower-priority "
            "complaint that becomes urgent (priority moves up) is re-bucketed and gets "
            "the new, shorter deadline."
        ),
    },
    {
        "title": "SLA monitoring and at-risk alerts",
        "section": "SLA - Monitoring",
        "category": KnowledgeCategory.SLA_POLICY,
        "source_ref": "Citizen Charter, §Monitoring (v2, 2026)",
        "content": (
            "Every open work order is monitored against its SLA deadline. As an order "
            "approaches its due time it is flagged at-risk and the assigned team and "
            "supervisors are notified; once the deadline passes it is flagged breached "
            "and the order is escalated for immediate attention. Monitoring computes "
            "deadline health from the order's sla_hours and due_at fields and never "
            "reports a live status when only an estimate is available."
        ),
    },
    {
        "title": "What each priority bucket means",
        "section": "SLA - Priority Buckets",
        "category": KnowledgeCategory.SLA_POLICY,
        "source_ref": "Citizen Charter, §Priority (v2, 2026)",
        "content": (
            "Complaints are prioritised on a 0-100 score into four buckets: P1 "
            "(score 80-100, critical), P2 (score 60-79, high), P3 (score 40-59, medium) "
            "and P4 (score below 40, low priority). P1 complaints are the most urgent "
            "and receive the fastest SLA. Higher buckets are not a judgement about the "
            "citizen - they reflect severity, public impact and required response speed."
        ),
    },
    {
        "title": "SLA breach escalation",
        "section": "SLA - Escalation",
        "category": KnowledgeCategory.SLA_POLICY,
        "source_ref": "Citizen Charter, §Escalation (v2, 2026)",
        "content": (
            "When a work order breaches its SLA deadline it is escalated: supervisors "
            "and the relevant department head are notified, the order can be "
            "reassigned to an available team, and its status is kept visible to the "
            "citizen in the complaint timeline. A citizen may raise the breach with "
            "their ward office, quoting their complaint reference number."
        ),
    },
    # ---- department responsibilities ------------------------------------- #
    {
        "title": "Water department responsibilities",
        "section": "Departments - Water",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Water (2026)",
        "content": (
            "The Water department handles water supply disruptions, pipe bursts, "
            "quality issues and water leaks. Complaints categorised as Water Supply or "
            "Water Leak are routed here. They should respond within the SLA set for "
            "the complaint's priority bucket."
        ),
    },
    {
        "title": "Roads department responsibilities",
        "section": "Departments - Roads",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Roads (2026)",
        "content": (
            "The Roads department maintains streets, footpaths, kerbs and road "
            "surfaces. Road condition complaints such as potholes are routed here. "
            "It also supports the Drainage department in flooding situations."
        ),
    },
    {
        "title": "Electrical department responsibilities",
        "section": "Departments - Electrical",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Electrical (2026)",
        "content": (
            "The Electrical department handles electricity supply issues and street "
            "lighting. Supply and Street Lighting complaints are routed here. Fallen "
            "or exposed live power lines are treated as a public-safety emergency and "
            "go to Emergency / Disaster response."
        ),
    },
    {
        "title": "Waste and sanitation department responsibilities",
        "section": "Departments - Waste",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Waste & Sanitation (2026)",
        "content": (
            "The Waste department runs garbage collection, bin management and "
            "general sanitation. Garbage and Sanitation complaints are routed here, "
            "including overflowing bins and missed collections."
        ),
    },
    {
        "title": "Drainage department responsibilities",
        "section": "Departments - Drainage",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Drainage (2026)",
        "content": (
            "The Drainage department manages storm-water drains, flooding and blocked "
            "drain lines. Drainage and Flooding complaints are routed here, with the "
            "Roads department as a supporting department where street access is needed."
        ),
    },
    {
        "title": "Parks department responsibilities",
        "section": "Departments - Parks",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Parks (2026)",
        "content": (
            "The Parks department maintains parks, gardens, playgrounds and trees. "
            "Parks complaints and fallen trees that are not blocking public safety "
            "are routed here."
        ),
    },
    {
        "title": "Emergency and disaster response",
        "section": "Departments - Emergency",
        "category": KnowledgeCategory.DEPARTMENT_RESPONSIBILITY,
        "source_ref": "Department Handbook, Emergency & Disaster (2026)",
        "content": (
            "Emergency / Disaster response covers public-safety hazards, accident-prone "
            "locations and disaster response. Public-safety complaints and fallen "
            "electrical lines are routed here and treated with maximum priority."
        ),
    },
    # ---- complaint categories -------------------------------------------- #
    {
        "title": "Road complaint category",
        "section": "Complaint Categories - Roads",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Road (2026)",
        "content": (
            "The Road category covers potholes, damaged road surfaces, broken kerbs "
            "and footpath issues. These complaints are routed to the Roads department."
        ),
    },
    {
        "title": "Sanitation complaint category",
        "section": "Complaint Categories - Sanitation",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Sanitation (2026)",
        "content": (
            "The Sanitation category covers garbage, overflowing bins and missed waste "
            "collections. These complaints are routed to the Waste department."
        ),
    },
    {
        "title": "Water complaint category",
        "section": "Complaint Categories - Water",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Water (2026)",
        "content": (
            "The Water category covers water supply disruptions, pipe bursts and water "
            "quality concerns. Water leaks are a distinct sub-category; both are routed "
            "to the Water department."
        ),
    },
    {
        "title": "Electricity complaint category",
        "section": "Complaint Categories - Electricity",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Electricity (2026)",
        "content": (
            "The Electricity category covers supply outages and faults. Fallen or "
            "exposed live wires are emergencies and go straight to Emergency / "
            "Disaster response for the highest priority handling."
        ),
    },
    {
        "title": "Public safety complaint category",
        "section": "Complaint Categories - Public Safety",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Public Safety (2026)",
        "content": (
            "The Public Safety category covers hazards, accident-prone spots and "
            "community-threatening situations. These complaints are routed to "
            "Emergency / Disaster response with priority handling."
        ),
    },
    {
        "title": "Parks complaint category",
        "section": "Complaint Categories - Parks",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Parks (2026)",
        "content": (
            "The Parks category covers park upkeep, broken playground equipment and "
            "trees. Fallen trees that do not create an immediate hazard are routed to "
            "the Parks department."
        ),
    },
    {
        "title": "Street lighting complaint category",
        "section": "Complaint Categories - Street Lighting",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Street Lighting (2026)",
        "content": (
            "The Street Lighting category covers broken or flickering street lights. "
            "These complaints are routed to the Electrical department."
        ),
    },
    {
        "title": "Drainage and flooding complaint category",
        "section": "Complaint Categories - Drainage",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Drainage (2026)",
        "content": (
            "The Drainage category covers blocked drains and storm-water flooding. "
            "These complaints are routed to the Drainage department, supported by the "
            "Roads department where street work is needed."
        ),
    },
    {
        "title": "Other complaint category",
        "section": "Complaint Categories - Other",
        "category": KnowledgeCategory.COMPLAINT_CATEGORY,
        "source_ref": "Complaint Lodging Guide, Other (2026)",
        "content": (
            "If a complaint does not clearly fit a standard category it is logged as "
            "Other. Such complaints are reviewed and routed to the most appropriate "
            "department based on the description and location."
        ),
    },
    # ---- citizen FAQ ------------------------------------------------------ #
    {
        "title": "What does P1 priority mean",
        "section": "FAQ - Priority",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Priority (2026)",
        "content": (
            "P1 is the highest priority bucket: it means the council scored the "
            "complaint 80-100/100 for severity and public impact. P1 complaints receive "
            "a 24-hour SLA once their work order is approved. If your complaint is "
            "bucketed P1 you will see this in its priority history with the numeric "
            "score and the factors that drove it."
        ),
    },
    {
        "title": "How a citizen tracks a complaint",
        "section": "FAQ - Tracking",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Tracking (2026)",
        "content": (
            "Every complaint moves through a tracked lifecycle: Submitted, AI "
            "analysis, Evidence verified, Ward identified, Prioritised, Department "
            "assigned, Work order created, Worker assigned, In progress, Resolved and "
            "Closed. The complaint timeline shows this journey with timestamps, "
            "assigned department, priority and any worker notes."
        ),
    },
    {
        "title": "Who handles a citizen complaint",
        "section": "FAQ - Department routing",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Routing (2026)",
        "content": (
            "A complaint is routed to one of seven departments based on its category: "
            "Water, Roads, Electrical, Waste, Drainage, Parks or Emergency / Disaster. "
            "An officer can override the automatic routing when needed. You can see "
            "the currently responsible department in the complaint's timeline."
        ),
    },
    {
        "title": "What is a ward",
        "section": "FAQ - Wards",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Wards (2026)",
        "content": (
            "A ward is an administrative division of the city used to organise "
            "governance, complaints and municipal services. Your complaint is "
            "automatically linked to the ward identified from its location, and ward "
            "level statistics - such as the most common complaint categories - are "
            "used to plan response effort."
        ),
    },
    {
        "title": "Work order and repair timeline",
        "section": "FAQ - Work Orders",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Work Orders (2026)",
        "content": (
            "After a complaint is prioritised and routed, a work order is drafted, an "
            "officer approves it, a field worker is assigned and the repair is "
            "performed. The citizen can see the work order's creation date, department, "
            "status and completion in the complaint timeline."
        ),
    },
    {
        "title": "How a complaint is verified and closed",
        "section": "FAQ - Verification",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Verification (2026)",
        "content": (
            "Before a complaint closes, the repair is checked: the worker submits "
            "before and after photos and an AI verification compares them. High "
            "confidence verified results are accepted; lower confidence or critical "
            "priority cases require a human reviewer. The complaint then requires "
            "citizen confirmation before it is fully closed."
        ),
    },
    {
        "title": "How to escalate a complaint",
        "section": "FAQ - Escalation",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Escalation (2026)",
        "content": (
            "If a complaint is not progressing you can contact the assigned department "
            "or your ward office with your complaint reference number. SLA-breach and "
            "P1 (critical) complaints are automatically escalated: supervisors are "
            "notified and the order can be reassigned to an available team."
        ),
    },
    {
        "title": "Common issues reported by citizens",
        "section": "FAQ - Common Issues",
        "category": KnowledgeCategory.CITIZEN_FAQ,
        "source_ref": "Citizen FAQ, Common Issues (2026)",
        "content": (
            "The most reported civic issues are typically garbage collection, road "
            "condition, and water supply followed by drainage and street lighting. "
            "The assistant can tell you the most common categories reported in your own "
            "ward based on actual complaint records."
        ),
    },
    # ---- municipal procedure ---------------------------------------------- #
    {
        "title": "Complaint lifecycle procedures",
        "section": "Procedure - Lifecycle",
        "category": KnowledgeCategory.MUNICIPAL_PROCEDURE,
        "source_ref": "Complaint Handling SOP v4, §Lifecycle (2026)",
        "content": (
            "The standard complaint lifecycle is: submitted by the citizen, AI "
            "analysis (category + severity), evidence verified (photos/video), ward "
            "identified from location, prioritised (score + bucket), department "
            "assigned, work order created, worker assigned, in progress, resolved, "
            "citizen verified and closed. Each transition is recorded in the "
            "complaint status history."
        ),
    },
    {
        "title": "How complaint priority is computed",
        "section": "Procedure - Priority Engine",
        "category": KnowledgeCategory.MUNICIPAL_PROCEDURE,
        "source_ref": "Complaint Handling SOP v4, §Priority (2026)",
        "content": (
            "Priority is computed by a deterministic engine, never by an AI model. "
            "It scores a complaint 0-100 using weighted factors: severity, weather "
            "conditions, location (proximity to sensitive facilities), crowd impact "
            "(population at risk + report volume), historical recurrence in the area "
            "and time already unresolved. Scores map to buckets P1 to P4, and every "
            "score change is stored in the complaint's priority history with its "
            "factor breakdown."
        ),
    },
    {
        "title": "Evidence verification procedures",
        "section": "Procedure - Evidence",
        "category": KnowledgeCategory.MUNICIPAL_PROCEDURE,
        "source_ref": "Complaint Handling SOP v4, §Evidence (2026)",
        "content": (
            "Citizens may attach photos or short videos when lodging a complaint. An "
            "AI image analysis verifies the evidence matches the stated issue. When "
            "the AI cannot decide confidently, or the issue is critical priority, the "
            "submission goes to human review before proceeding."
        ),
    },
    {
        "title": "Ward identification procedure",
        "section": "Procedure - Ward",
        "category": KnowledgeCategory.MUNICIPAL_PROCEDURE,
        "source_ref": "Complaint Handling SOP v4, §Ward (2026)",
        "content": (
            "The complaint's location is used to identify its ward automatically. If "
            "an address is supplied it is reverse-geocoded; when a precise location "
            "is unavailable the system falls back to the citizen's registered ward. "
            "Ward identification drives local statistics and routing context."
        ),
    },
    {
        "title": "Work order creation and dispatch procedure",
        "section": "Procedure - Dispatch",
        "category": KnowledgeCategory.MUNICIPAL_PROCEDURE,
        "source_ref": "Complaint Handling SOP v4, §Dispatch (2026)",
        "content": (
            "Once a complaint is prioritised and routed, a work order draft is "
            "created with the responsible department, a recommended action and an "
            "estimated response time. An authorized officer approves the draft, then "
            "the most suitable available field worker is assigned. The officer may "
            "reassign, escalate, reject or hold the order."
        ),
    },
    {
        "title": "Repair verification and closure procedure",
        "section": "Procedure - Closure",
        "category": KnowledgeCategory.MUNICIPAL_PROCEDURE,
        "source_ref": "Complaint Handling SOP v4, §Closure (2026)",
        "content": (
            "After the field worker completes a repair, before/after photos are "
            "compared by an AI verification agent. Verified repairs proceed; "
            "partially-resolved or unresolved repairs are reopened for follow-up, and "
            "all critical priority repairs require a human reviewer. The complaint is "
            "closed only after the citizen confirms the issue is resolved."
        ),
    },
]


async def ensure_knowledge_base(
    db: AsyncSession,
    embedder: object | None = None,
) -> int:
    """Idempotently upsert ``KNOWLEDGE_DOCUMENTS`` by title, embedding each.

    Returns the number of documents ensured (created or refreshed). The heavy
    local embedding runs through :class:`EmbeddingService` (threadpool) unless an
    overridable ``embedder`` (e.g. a deterministic test fake) is supplied.
    """
    service = embedder or EmbeddingService()
    ensured = 0
    for doc in KNOWLEDGE_DOCUMENTS:
        existing = await db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.title == doc["title"])
        )
        raw = f"{doc['title']}\n{doc['content']}"
        embedding = await service.embed_text(raw)
        if existing is None:
            db.add(
                KnowledgeDocument(
                    title=doc["title"],
                    section=doc["section"],
                    category=doc["category"],
                    content=doc["content"],
                    source_ref=doc["source_ref"],
                    is_active=True,
                    embedding=embedding,
                )
            )
        else:
            existing.section = doc["section"]
            existing.category = doc["category"]
            existing.content = doc["content"]
            existing.source_ref = doc["source_ref"]
            existing.is_active = True
            existing.embedding = embedding
        ensured += 1
    await db.commit()
    return ensured
