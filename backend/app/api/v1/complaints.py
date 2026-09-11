"""Multimodal complaint submission API (Part 4).

Flow:
1. Client uploads each image/short video via POST /complaints/media (one file
   per request) → gets a media id back (per-file progress + retry support).
2. Client submits POST /complaints with description, category, media_ids and a
   location, creating the complaint and linking the uploaded media + PostGIS point.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import Complaint, User
from app.models.enums import RoleName
from app.schemas.complaint import (
    ComplaintCreateIn,
    ComplaintCreateOut,
    ComplaintDetailOut,
    ComplaintMediaOut,
    ComplaintTimelineOut,
)
from app.schemas.context import (
    ContextRunIn,
    ContextRunOut,
    ContextRunResponse,
)
from app.schemas.correlation import (
    CorrelationMatch,
    CorrelationRunIn,
    CorrelationRunOut,
    CorrelationRunResponse,
)
from app.schemas.priority import (
    PriorityHistoryOut,
    PriorityRunIn,
    PriorityRunOut,
    PriorityRunResponse,
)
from app.schemas.routing import (
    DepartmentOverrideHistoryOut,
    DepartmentOverrideIn,
    DepartmentOverrideResponse,
    RoutingHistoryOut,
    RoutingRunIn,
    RoutingRunOut,
    RoutingRunResponse,
)
from app.schemas.triage import AgentRunOut, TriageInput, TriageRunIn, TriageRunResponse
from app.schemas.vision import VisionRunIn, VisionRunOut, VisionRunResponse
from app.services import (
    complaint_service,
    complaint_tracking_service,
    context_service,
    correlation_service,
    priority_service,
    routing_service,
    triage_service,
    vision_service,
)
from app.services.audit_service import ACTION_COMPLAINT_CREATE, record_audit

router = APIRouter(prefix="/complaints", tags=["complaints"])

# Officer-only operational endpoints (AI triage/vision/correlation/context/
# priority/routing + dispatch + work orders). Citizens view their complaint via
# the detail + timeline endpoints only; this callable keeps internal analysis
# and recommendation data out of citizen-accessible API responses.
_OPERATIONAL_DEPS = require_roles(
    RoleName.OFFICER.value,
    RoleName.ADMIN.value,
    RoleName.WARD_REPRESENTATIVE.value,
)


def _handle_upload_error(exc: complaint_service.MediaValidationError) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/media",
    response_model=ComplaintMediaOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(RoleName.CITIZEN.value))],
)
async def upload_media(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintMediaOut:
    """Upload a single image or short video and store it in object storage.

    The returned ``id`` is referenced by a later complaint submission.
    """
    data = await file.read()
    try:
        media = await complaint_service.validate_and_store_media(
            user, file.content_type, file.filename or "upload", data
        )
    except complaint_service.MediaValidationError as exc:
        raise _handle_upload_error(exc) from exc
    except Exception as exc:  # storage/network failures surface as a clean 500
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Upload storage is unavailable."
        ) from exc

    db.add(media)
    await db.commit()
    await db.refresh(media)
    return complaint_service.media_out(media)


@router.post(
    "",
    response_model=ComplaintCreateOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(RoleName.CITIZEN.value))],
)
async def create_complaint(
    request: Request,
    payload: ComplaintCreateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintCreateOut:
    """Create a complaint from description/category/optional media/location."""
    try:
        complaint = await complaint_service.create_complaint(db, user, payload)
    except complaint_service.MediaValidationError as exc:
        raise _handle_upload_error(exc) from exc
    await record_audit(
        db,
        actor_id=user.id,
        action=ACTION_COMPLAINT_CREATE,
        entity_type="complaint",
        entity_id=str(complaint.id),
        after={
            "category": complaint.category.value,
            "priority": complaint.priority.value,
            "status": complaint.status.value,
        },
        ip_address=request.client.host if request.client else None,
    )
    await db.commit()
    return ComplaintCreateOut(
        id=complaint.id,
        category=complaint.category,
        title=complaint.title,
        description=complaint.description,
        location=complaint.location,
        priority=complaint.priority.value,
        status=complaint.status.value,
        user_id=complaint.user_id,
        language=complaint.language,
        created_at=complaint.created_at,
        media=[complaint_service.media_out(m) for m in complaint.media],
    )


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Complaint not found.")


def _access_denied() -> HTTPException:
    return HTTPException(status.HTTP_403_FORBIDDEN, "You cannot access this complaint.")


def _tracking_error(exc: Exception) -> HTTPException:
    if isinstance(exc, complaint_tracking_service.ComplaintNotFoundError):
        return _not_found()
    if isinstance(exc, complaint_tracking_service.ComplaintAccessError):
        return _access_denied()
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get(
    "/{complaint_id}",
    response_model=ComplaintDetailOut,
)
async def complaint_detail(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintDetailOut:
    """Return a single complaint including media, location, ward and priority."""
    try:
        return await complaint_tracking_service.get_complaint_detail(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _tracking_error(exc) from exc


@router.get(
    "/{complaint_id}/timeline",
    response_model=ComplaintTimelineOut,
)
async def complaint_timeline(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ComplaintTimelineOut:
    """Return the append-only status history (timeline) for a complaint."""
    try:
        return await complaint_tracking_service.get_complaint_timeline(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _tracking_error(exc) from exc


def _triage_error(exc: Exception) -> HTTPException:
    if isinstance(exc, triage_service.TriageNotFoundError):
        return _not_found()
    if isinstance(exc, triage_service.TriageAccessError):
        return _access_denied()
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/triage",
    response_model=TriageRunResponse,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def run_complaint_triage(
    complaint_id: uuid.UUID,
    payload: TriageRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TriageRunResponse:
    """Run the AI triage agent against a complaint (Part 7).

    The description / category / location are read from the stored complaint;
    only the language can be supplied by the caller. On success the complaint is
    advanced to PRIORITIZED. On provider failure the run is marked FAILED and
    nothing is destroyed, so the caller may retry.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    # Build the triage input from real complaint data. The language defaults from
    # the complaint's stored language (Part 26) so a complaint lodged in
    # Hindi/Marathi is triaged in that language even when the caller sends none.
    language = (payload.language if payload is not None else None) or None
    if not language and complaint.language:
        language = complaint.language
    language = language or "en"
    input_data = TriageInput(
        description=complaint.description or complaint.title,
        category=complaint.category,
        location=complaint.location,
        language=language,
    )
    try:
        return await triage_service.run_triage(db, user, complaint_id, input_data)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _triage_error(exc) from exc


@router.get(
    "/{complaint_id}/ai-triage",
    response_model=AgentRunOut | None,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_ai_triage(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> AgentRunOut | None:
    """Return the most recent successful/failed triage run for a complaint."""
    try:
        return await triage_service.get_latest_analysis(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _triage_error(exc) from exc


def _vision_error(exc: Exception) -> HTTPException:
    if isinstance(exc, vision_service.VisionNotFoundError):
        return _not_found()
    if isinstance(exc, vision_service.VisionAccessError):
        return _access_denied()
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/vision",
    response_model=VisionRunResponse,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def run_complaint_vision(
    complaint_id: uuid.UUID,
    payload: VisionRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VisionRunResponse:
    """Run the AI evidence-verification (vision) agent against a complaint (Part 8).

    The agent analyzes the complaint's attached images against its description
    using the configured multimodal model. On success the complaint advances to
    EVIDENCE_VERIFIED; mismatches / low confidence are flagged for human review
    and low-confidence or failed runs never close the complaint. Provider or
    image failures mark the run FAILED and leave the complaint intact for retry.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    try:
        return await vision_service.run_vision(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _vision_error(exc) from exc


@router.get(
    "/{complaint_id}/vision-result",
    response_model=VisionRunOut | None,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_vision_result(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> VisionRunOut | None:
    """Return the most recent vision verification run for a complaint."""
    try:
        return await vision_service.get_vision_result(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _vision_error(exc) from exc


def _correlation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, correlation_service.CorrelationNotFoundError):
        return _not_found()
    if isinstance(exc, correlation_service.CorrelationAccessError):
        return _access_denied()
    if isinstance(exc, correlation_service.CandidateNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, "Correlation link not found.")
    if isinstance(exc, correlation_service.CandidateDecidedError):
        return HTTPException(
            status.HTTP_409_CONFLICT, "This correlation link has already been decided."
        )
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/correlate",
    response_model=CorrelationRunResponse,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def run_complaint_correlation(
    complaint_id: uuid.UUID,
    payload: CorrelationRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CorrelationRunResponse:
    """Run the duplicate / incident correlation agent against a complaint (Part 9).

    The agent embeds the complaint's text with a local Sentence Transformer and
    searches for possible duplicates using semantic (pgvector), geospatial
    (PostGIS) and temporal signals. When a likely match is found the complaint is
    flagged ``POSSIBLE_DUPLICATE`` and candidates are surfaced for an officer to
    Confirm or Reject. Embedding failures mark the run ``FAILED`` and leave the
    complaint intact so it can be retried.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    try:
        return await correlation_service.run_correlation(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _correlation_error(exc) from exc


@router.get(
    "/{complaint_id}/correlation-result",
    response_model=CorrelationRunOut | None,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_correlation_result(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CorrelationRunOut | None:
    """Return the most recent correlation run for a complaint."""
    try:
        return await correlation_service.get_correlation_result(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _correlation_error(exc) from exc


@router.get(
    "/{complaint_id}/correlations",
    response_model=list[CorrelationMatch],
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def list_complaint_correlations(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CorrelationMatch]:
    """Return the candidate duplicate links for a complaint."""
    try:
        return await correlation_service.list_candidates(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _correlation_error(exc) from exc


@router.post(
    "/correlations/{correlation_id}/confirm",
    response_model=CorrelationMatch,
    dependencies=[
        Depends(
            require_roles(
                RoleName.OFFICER.value,
                RoleName.ADMIN.value,
                RoleName.WARD_REPRESENTATIVE.value,
            )
        )
    ],
)
async def confirm_complaint_correlation(
    correlation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CorrelationMatch:
    """Officer: confirm that a candidate link is a genuine duplicate."""
    try:
        return await correlation_service.decide_candidate(db, user, correlation_id, confirm=True)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _correlation_error(exc) from exc


@router.post(
    "/correlations/{correlation_id}/reject",
    response_model=CorrelationMatch,
    dependencies=[
        Depends(
            require_roles(
                RoleName.OFFICER.value,
                RoleName.ADMIN.value,
                RoleName.WARD_REPRESENTATIVE.value,
            )
        )
    ],
)
async def reject_complaint_correlation(
    correlation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CorrelationMatch:
    """Officer: reject a candidate link as a false positive."""
    try:
        return await correlation_service.decide_candidate(db, user, correlation_id, confirm=False)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _correlation_error(exc) from exc


def _context_error(exc: Exception) -> HTTPException:
    if isinstance(exc, context_service.ContextNotFoundError):
        return _not_found()
    if isinstance(exc, context_service.ContextAccessError):
        return _access_denied()
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/context",
    response_model=ContextRunResponse,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def run_complaint_context(
    complaint_id: uuid.UUID,
    payload: ContextRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContextRunResponse:
    """Run the context enrichment agent against a complaint (Part 11).

    The deterministic (no-LLM) agent fuses weather (Open-Meteo, Redis-cached),
    GIS + nearby critical infrastructure (Part 10 reuse), and historical
    complaint volume into a structured ``ContextOutput`` persisted to
    ``agent_runs`` (``agent="context"``). Every external source records
    provenance (name, params, retrieval time). Individual upstream failures
    degrade gracefully rather than fail the run.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    try:
        return await context_service.run_context(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _context_error(exc) from exc


@router.get(
    "/{complaint_id}/context-result",
    response_model=ContextRunOut | None,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_context_result(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContextRunOut | None:
    """Return the most recent context enrichment run for a complaint."""
    try:
        return await context_service.get_context_result(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _context_error(exc) from exc


def _priority_error(exc: Exception) -> HTTPException:
    if isinstance(exc, priority_service.PriorityNotFoundError):
        return _not_found()
    if isinstance(exc, priority_service.PriorityAccessError):
        return _access_denied()
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/priority",
    response_model=PriorityRunResponse,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def run_complaint_priority(
    complaint_id: uuid.UUID,
    payload: PriorityRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriorityRunResponse:
    """Run the deterministic priority & risk engine against a complaint (Part 12).

    Aggregate the seven priority inputs (severity, population impact, critical
    infrastructure proximity, weather, complaint count, historical recurrence and
    time unresolved) into a single 0..100 score and a ``DynamicPriority`` bucket
    using a *deterministic* weighted formula — the LLM never sets the numeric
    score. The result persists to ``agent_runs`` (``agent="priority"``) and appends
    a ``complaint_priority_history`` row so the UI can show a score history.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    try:
        return await priority_service.run_priority(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _priority_error(exc) from exc


@router.get(
    "/{complaint_id}/priority-result",
    response_model=PriorityRunOut | None,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_priority_result(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriorityRunOut | None:
    """Return the most recent priority engine run for a complaint."""
    try:
        return await priority_service.get_priority_result(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _priority_error(exc) from exc


@router.get(
    "/{complaint_id}/priority-history",
    response_model=PriorityHistoryOut,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_priority_history(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> PriorityHistoryOut:
    """Return the append-only priority score history for a complaint."""
    try:
        return await priority_service.get_priority_history(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _priority_error(exc) from exc


def _routing_error(exc: Exception) -> HTTPException:
    if isinstance(exc, routing_service.RoutingNotFoundError):
        return _not_found()
    if isinstance(exc, routing_service.RoutingAccessError):
        return _access_denied()
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.post(
    "/{complaint_id}/routing",
    response_model=RoutingRunResponse,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def run_complaint_routing(
    complaint_id: uuid.UUID,
    payload: RoutingRunIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoutingRunResponse:
    """Run the deterministic department routing agent against a complaint (Part 13).

    The no-LLM agent fuses the complaint's category with the latest triage / vision /
    priority / context runs to recommend one of the seven fixed departments (Water,
    Roads, Electrical, Waste, Drainage, Parks, Emergency/Disaster), optional
    secondary departments for multi-department issues, an explainable reason and a
    deterministic confidence. The decision persists to ``agent_runs``
    (``agent="routing"``) and appends a ``complaint_department_history`` row.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    try:
        return await routing_service.run_routing(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _routing_error(exc) from exc


@router.get(
    "/{complaint_id}/routing-result",
    response_model=RoutingRunOut | None,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_routing_result(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoutingRunOut | None:
    """Return the most recent routing agent run for a complaint."""
    try:
        return await routing_service.get_routing_result(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _routing_error(exc) from exc


@router.get(
    "/{complaint_id}/routing-history",
    response_model=RoutingHistoryOut,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_routing_history(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RoutingHistoryOut:
    """Return the append-only routing-decision history for a complaint."""
    try:
        return await routing_service.get_routing_history(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _routing_error(exc) from exc


@router.post(
    "/{complaint_id}/routing/override",
    response_model=DepartmentOverrideResponse,
    dependencies=[
        Depends(
            require_roles(
                RoleName.OFFICER.value,
                RoleName.ADMIN.value,
                RoleName.WARD_REPRESENTATIVE.value,
            )
        )
    ],
)
async def override_complaint_department(
    complaint_id: uuid.UUID,
    payload: DepartmentOverrideIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DepartmentOverrideResponse:
    """Officer: override a complaint's assigned department (Part 13).

    Records the old department, the new one, the officer's reason, who did it and
    when into ``department_overrides``; the audit trail is append-only.
    """
    complaint = await db.get(Complaint, complaint_id)
    if complaint is None:
        raise _not_found()
    try:
        return await routing_service.override_department(
            db,
            user,
            complaint_id,
            new_department=payload.new_department,
            reason=payload.reason,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _routing_error(exc) from exc


@router.get(
    "/{complaint_id}/routing/overrides",
    response_model=DepartmentOverrideHistoryOut,
    dependencies=[Depends(_OPERATIONAL_DEPS)],
)
async def get_complaint_routing_overrides(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DepartmentOverrideHistoryOut:
    """Return all recorded officer department overrides for a complaint."""
    try:
        return await routing_service.get_override_history(db, user, complaint_id)
    except Exception as exc:  # noqa: BLE001 - mapped to the right HTTP status
        raise _routing_error(exc) from exc
