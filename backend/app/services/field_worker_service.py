"""Service layer for the Field Worker Application (Part 18).

The field worker logs in (same auth as everyone else — their account's role is
FIELD_WORKER and they have a linked ``FieldWorker`` profile). They see a
mobile-first dashboard of their assigned jobs plus nearby / P1 work, and walk a
guided workflow:

    accept → navigate (GPS check-in) → arrive (GPS check-in) → start
    → before photo → repair → after photo → notes → complete

Every step is recorded on the server as an append-only ``WorkOrderActivity``
row (with optional GPS capture and a ``geo_denied`` flag when the device
location was unavailable — coordinates are only ever stored during an explicit
check-in, never tracked continuously). Client-issued ``client_ref`` values make
each action idempotent so the offline queue can be re-synced safely: re-playing
a queued action with the same ``client_ref`` returns the existing state instead
of duplicating activity rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.core.notification_types import EVENT_REPAIR_STARTED, EVENT_RESOLVED
from app.models import (
    Complaint,
    FieldWorker,
    Role,
    User,
    WorkOrder,
    WorkOrderActivity,
    WorkOrderPhoto,
    WorkOrderStatusHistory,
)
from app.models.enums import (
    AssignmentStatus,
    ComplaintStatus,
    RoleName,
    WorkOrderAction,
    WorkOrderStatus,
)
from app.schemas.field_worker import (
    WorkerDashboardOut,
    WorkerJobOut,
    WorkerOrderDetailOut,
    WorkOrderActivityOut,
    WorkOrderPhotoOut,
)
from app.services import notification_service, sla_service
from app.services.complaint_service import (
    MediaValidationError,
    _classify_content_type,
    _extension_for,
    _split_allowed,
    _validate_image,
    _validate_video,
    record_status_transition,
)
from app.services.dispatch_engine import haversine_km
from app.storage import get_storage

_IDLE_STATUSES = (
    WorkOrderStatus.COMPLETED,
    WorkOrderStatus.CLOSED,
    WorkOrderStatus.REJECTED,
)


class WorkerProfileError(Exception):
    """Raised when the user has no linked field-worker profile."""


class WorkerOrderNotFoundError(Exception):
    """Raised when a work order does not exist or is not visible to the caller."""


class WorkerOrderStateError(Exception):
    """Raised when a workflow action is illegal for the current job state."""


def _now() -> datetime:
    return datetime.now(UTC)


def _photo_out(photo: WorkOrderPhoto) -> WorkOrderPhotoOut:
    return WorkOrderPhotoOut(
        id=photo.id,
        category=photo.category,
        original_filename=photo.original_filename,
        content_type=photo.content_type,
        size_bytes=photo.size_bytes,
        allowed=photo.allowed,
        url=get_storage().url(photo.storage_key),
        created_at=photo.created_at,
    )


def _activity_out(activity: WorkOrderActivity) -> WorkOrderActivityOut:
    return WorkOrderActivityOut(
        id=activity.id,
        activity_type=activity.activity_type,
        note=activity.note,
        latitude=activity.latitude,
        longitude=activity.longitude,
        geo_denied=activity.geo_denied,
        media_id=activity.media_id,
        worker_name=activity.worker.user.full_name
        if activity.worker is not None and activity.worker.user is not None
        else None,
        recorded_at=activity.recorded_at,
    )


async def _require_profile(db: AsyncSession, user: User) -> FieldWorker:
    worker = await db.scalar(
        select(FieldWorker)
        .where(FieldWorker.user_id == user.id)
        .options(selectinload(FieldWorker.user))
    )
    if worker is None:
        raise WorkerProfileError("No field worker profile is linked to this account.")
    return worker


def _is_mine(order: WorkOrder, worker: FieldWorker) -> bool:
    return order.worker_id == worker.id


async def _load_order(db: AsyncSession, order_id: uuid.UUID) -> WorkOrder | None:
    return await db.scalar(
        select(WorkOrder)
        .where(WorkOrder.id == order_id)
        .execution_options(populate_existing=True)
        .options(
            selectinload(WorkOrder.worker).selectinload(FieldWorker.user),
            selectinload(WorkOrder.complaint),
            selectinload(WorkOrder.status_history).selectinload(WorkOrderStatusHistory.actor),
            selectinload(WorkOrder.assignments),
            selectinload(WorkOrder.activities)
            .selectinload(WorkOrderActivity.worker)
            .selectinload(FieldWorker.user),
            selectinload(WorkOrder.photos),
        )
    )


async def _require_my_order(
    db: AsyncSession, order_id: uuid.UUID, worker: FieldWorker
) -> WorkOrder:
    order = await _load_order(db, order_id)
    if order is None:
        raise WorkerOrderNotFoundError("Work order not found.")
    if not _is_mine(order, worker):
        raise WorkerOrderNotFoundError("Work order not found.")  # do not leak others' jobs
    return order


def _distance_m(order: WorkOrder, ref_lat: float | None, ref_lon: float | None) -> float | None:
    if (
        ref_lat is None
        or ref_lon is None
        or order.location_lat is None
        or order.location_lon is None
    ):
        return None
    return round(haversine_km(ref_lat, ref_lon, order.location_lat, order.location_lon) * 1000, 1)


def _job_out(
    order: WorkOrder,
    ref_lat: float | None,
    ref_lon: float | None,
    sla=None,
) -> WorkerJobOut:
    has_before = any(p.category == "BEFORE" for p in order.photos)
    has_after = any(p.category == "AFTER" for p in order.photos)
    return WorkerJobOut(
        id=order.id,
        complaint_id=order.complaint_id,
        incident=order.incident,
        department=order.department,
        priority=order.priority,
        status=order.status,
        address=order.address,
        location_lat=order.location_lat,
        location_lon=order.location_lon,
        due_at=order.due_at,
        eta_minutes=order.eta_minutes,
        distance_m=_distance_m(order, ref_lat, ref_lon),
        accepted_at=order.accepted_at,
        started_at=order.started_at,
        completed_at=order.completed_at,
        worker_notes=order.worker_notes,
        has_before_photo=has_before,
        has_after_photo=has_after,
        sla_state=sla.state if sla is not None else "ON_TRACK",
        sla_progress=sla.progress if sla is not None else 0.0,
        sla_remaining_seconds=sla.remaining_seconds if sla is not None else None,
        sla_remaining_human=sla.remaining_human if sla is not None else None,
    )


def _complaint_category(order: WorkOrder) -> str | None:
    if order.complaint is None:
        return None
    cat = order.complaint.category
    return cat.value if hasattr(cat, "value") else str(cat)


async def _sla_for(db: AsyncSession, order: WorkOrder) -> object | None:
    """SLA snapshot used by the worker UI (read-only, resolves the rulebook)."""
    return await sla_service.compute_snapshot(
        db,
        order,
        now=_now(),
        category=_complaint_category(order),
        backfill=False,
    )


async def _record_activity(
    db: AsyncSession,
    order: WorkOrder,
    worker: FieldWorker,
    activity_type: str,
    *,
    note: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    geo_denied: bool = False,
    media_id: uuid.UUID | None = None,
    client_ref: str | None = None,
) -> WorkOrderActivity | None:
    """Append the workflow activity, deduplicating on ``(worker_id, client_ref)``.

    Returns ``None`` when the activity was already recorded (idempotent replay of
    an offline-queued action) — the caller treats that as "no-op, state is the
    same as what the client already has".
    """
    if client_ref:
        existing = await db.scalar(
            select(WorkOrderActivity).where(
                WorkOrderActivity.worker_id == worker.id,
                WorkOrderActivity.client_ref == client_ref,
            )
        )
        if existing is not None:
            return None
    activity = WorkOrderActivity(
        work_order_id=order.id,
        worker_id=worker.id,
        activity_type=activity_type,
        note=note,
        latitude=latitude,
        longitude=longitude,
        geo_denied=geo_denied,
        media_id=media_id,
        client_ref=client_ref,
    )
    db.add(activity)
    return activity


async def _notify_repair_started(db: AsyncSession, order: WorkOrder) -> None:
    """Notify the complaint owner that repair work has started (Part 21)."""
    if order.complaint is None:
        return
    owner = await db.get(User, order.complaint.user_id)
    if owner is None or not owner.is_active:
        return
    await notification_service.notify(
        db,
        targets=[owner],
        event=EVENT_REPAIR_STARTED,
        complaint_id=order.complaint_id,
        work_order_id=order.id,
        body=(
            f"Repair work for '{order.complaint.title}' has started "
            f"(a {order.worker.user.full_name or 'field worker'} is on site)."
            if order.worker is not None and order.worker.user is not None
            else f"Repair work for '{order.complaint.title}' has started."
        ),
        link=f"/dashboard/complaints/{order.complaint_id}",
    )


async def _notify_work_completed(db: AsyncSession, complaint: Complaint, order: WorkOrder) -> None:
    """Notify the complaint owner (+ ward representatives) the job is resolved (Part 21)."""
    link = f"/dashboard/complaints/{complaint.id}"
    owner = await db.get(User, complaint.user_id)
    if owner is not None and owner.is_active:
        await notification_service.notify(
            db,
            targets=[owner],
            event=EVENT_RESOLVED,
            complaint_id=complaint.id,
            work_order_id=order.id,
            body=f"Your complaint '{complaint.title}' was marked resolved.",
            link=link,
        )
    if complaint.ward_id is not None:
        reps = (
            (
                await db.execute(
                    select(User).where(
                        User.ward_id == complaint.ward_id,
                        User.is_active.is_(True),
                        User.role.has(Role.name == RoleName.WARD_REPRESENTATIVE.value),
                    )
                )
            )
            .scalars()
            .all()
        )
        if reps:
            await notification_service.notify(
                db,
                targets=[rep for rep in reps if rep.is_active],
                event=EVENT_RESOLVED,
                complaint_id=complaint.id,
                work_order_id=order.id,
                body=f"Work order for '{complaint.title}' was completed.",
                link=link,
            )


# --------------------------------------------------------------------------- #
# Dashboard + detail
# --------------------------------------------------------------------------- #
async def get_dashboard(
    db: AsyncSession,
    user: User,
    ref_lat: float | None = None,
    ref_lon: float | None = None,
) -> WorkerDashboardOut:
    """Build the four dashboard queues (assigned / nearby / P1 / completed).

    ``ref_lat``/``ref_lon`` are the worker's device GPS (optional); fall back to
    the worker's home base so nearby rankings still work without a live fix.
    """
    worker = await _require_profile(db, user)
    if ref_lat is None or ref_lon is None:
        ref_lat, ref_lon = worker.home_latitude, worker.home_longitude

    mine = (
        (
            await db.execute(
                select(WorkOrder)
                .where(WorkOrder.worker_id == worker.id)
                .order_by(WorkOrder.created_at.desc())
                .options(
                    selectinload(WorkOrder.complaint),
                    selectinload(WorkOrder.photos),
                )
            )
        )
        .scalars()
        .all()
    )

    assigned: list[WorkerJobOut] = []
    p1: list[WorkerJobOut] = []
    completed: list[WorkerJobOut] = []
    for order in mine:
        sla = await _sla_for(db, order)
        if order.status in _IDLE_STATUSES:
            completed.append(_job_out(order, ref_lat, ref_lon, sla))
        else:
            assigned.append(_job_out(order, ref_lat, ref_lon, sla))
            if order.status == WorkOrderStatus.ASSIGNED and (order.priority or "").startswith("P1"):
                p1.append(_job_out(order, ref_lat, ref_lon, sla))

    nearby: list[WorkerJobOut] = []
    if ref_lat is not None and ref_lon is not None:
        others = (
            (
                await db.execute(
                    select(WorkOrder)
                    .where(
                        WorkOrder.worker_id.is_(None),
                        WorkOrder.status.notin_(_IDLE_STATUSES + (WorkOrderStatus.ESCALATED,)),
                        WorkOrder.location_lat.is_not(None),
                        WorkOrder.location_lon.is_not(None),
                    )
                    .options(selectinload(WorkOrder.complaint), selectinload(WorkOrder.photos))
                )
            )
            .scalars()
            .all()
        )
        ranked = sorted(others, key=lambda o: _distance_m(o, ref_lat, ref_lon) or float("inf"))
        nearby = [_job_out(o, ref_lat, ref_lon, await _sla_for(db, o)) for o in ranked[:10]]

    return WorkerDashboardOut(assigned=assigned, nearby=nearby, p1=p1, completed=completed)


async def get_order_detail(
    db: AsyncSession, user: User, order_id: uuid.UUID
) -> WorkerOrderDetailOut:
    """Return the full worker-facing detail bundle (also used post-sync)."""
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    complaint = (
        order.complaint
        if order.complaint is not None
        else await db.get(Complaint, order.complaint_id)
    )
    sla = await _sla_for(db, order)
    return WorkerOrderDetailOut(
        work_order=_job_out(order, worker.home_latitude, worker.home_longitude, sla),
        complaint_id=order.complaint_id,
        complaint_title=complaint.title if complaint is not None else None,
        complaint_description=complaint.description if complaint is not None else None,
        complaint_status=complaint.status.value if complaint is not None else None,
        photos=[_photo_out(p) for p in order.photos],
        activities=[_activity_out(a) for a in order.activities],
        status_history=[
            {
                "action": h.action,
                "note": h.note,
                "recorded_at": h.recorded_at.isoformat(),
            }
            for h in order.status_history
        ],
    )


# --------------------------------------------------------------------------- #
# Workflow actions (all idempotent for the offline queue)
# --------------------------------------------------------------------------- #
async def accept_job(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    note: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    geo_denied: bool = False,
    client_ref: str | None = None,
) -> WorkerOrderDetailOut:
    """Worker accepts their assigned job.

    Records ``accepted_at`` on the order + active assignment and an ACCEPT
    activity. Idempotent — re-accepting a job returns the current state.
    """
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    if order.status == WorkOrderStatus.ASSIGNED:
        previous = await _record_activity(
            db,
            order,
            worker,
            "ACCEPT",
            note=note,
            latitude=latitude,
            longitude=longitude,
            geo_denied=geo_denied,
            client_ref=client_ref,
        )
        if previous is not None:
            order.accepted_at = _now()
            db.add(
                WorkOrderStatusHistory(
                    work_order_id=order.id,
                    action=WorkOrderAction.ACCEPT.value,
                    from_status=WorkOrderStatus.ASSIGNED,
                    to_status=WorkOrderStatus.ASSIGNED,
                    actor_id=user.id,
                    note=note or "Accepted by field worker.",
                )
            )
            for assignment in order.assignments:
                if (
                    assignment.status == AssignmentStatus.ASSIGNED
                    and assignment.accepted_at is None
                ):
                    assignment.accepted_at = _now()
            await db.commit()
    return await get_order_detail(db, user, order_id)


async def check_in(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    activity_type: str,
    latitude: float | None = None,
    longitude: float | None = None,
    geo_denied: bool = False,
    note: str | None = None,
    client_ref: str | None = None,
) -> WorkerOrderDetailOut:
    """Record a navigational GPS check-in (EN_ROUTE or ARRIVED).

    Coordinates are optional and only stored when the worker supplies them; when
    location is unavailable ``geo_denied`` records the fact instead.
    """
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    previous = await _record_activity(
        db,
        order,
        worker,
        activity_type,
        note=note,
        latitude=latitude,
        longitude=longitude,
        geo_denied=geo_denied,
        client_ref=client_ref,
    )
    if previous is not None:
        await db.commit()
    return await get_order_detail(db, user, order_id)


async def start_job(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    note: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    geo_denied: bool = False,
    client_ref: str | None = None,
) -> WorkerOrderDetailOut:
    """Mark the job as started → IN_PROGRESS (idempotent)."""
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    if order.status == WorkOrderStatus.COMPLETED or order.status == WorkOrderStatus.CLOSED:
        raise WorkerOrderStateError(f"Cannot start a work order in state {order.status}.")
    previous = await _record_activity(
        db,
        order,
        worker,
        "START_WORK",
        note=note,
        latitude=latitude,
        longitude=longitude,
        geo_denied=geo_denied,
        client_ref=client_ref,
    )
    if previous is not None:
        changed = order.status != WorkOrderStatus.IN_PROGRESS
        from_status = order.status
        order.status = WorkOrderStatus.IN_PROGRESS
        order.started_at = _now()
        db.add(
            WorkOrderStatusHistory(
                work_order_id=order.id,
                action=WorkOrderAction.START_WORK.value,
                from_status=from_status,
                to_status=WorkOrderStatus.IN_PROGRESS,
                actor_id=user.id,
                note=note or "Work started by field worker.",
            )
        )
        if changed:
            if (
                order.complaint is not None
                and order.complaint.status.value != ComplaintStatus.IN_PROGRESS.value
            ):
                order.complaint.status = ComplaintStatus.IN_PROGRESS
                db.add(
                    record_status_transition(
                        order.complaint,
                        ComplaintStatus.IN_PROGRESS,
                        actor_id=user.id,
                        note="Field work started.",
                    )
                )
            await _notify_repair_started(db, order)
        await db.commit()
    return await get_order_detail(db, user, order_id)


async def save_notes(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    notes: str,
    client_ref: str | None = None,
) -> WorkerOrderDetailOut:
    """Store free-text field notes (idempotent via client_ref)."""
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    previous = await _record_activity(
        db,
        order,
        worker,
        "NOTE_ADDED",
        note=notes,
        client_ref=client_ref,
    )
    if previous is not None:
        order.worker_notes = notes
        await db.commit()
    return await get_order_detail(db, user, order_id)


async def complete_job(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    notes: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    geo_denied: bool = False,
    client_ref: str | None = None,
) -> WorkerOrderDetailOut:
    """Complete the job → COMPLETED and resolve the complaint (idempotent)."""
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    if (
        order.status in (WorkOrderStatus.CLOSED, WorkOrderStatus.REJECTED)
        or order.status == WorkOrderStatus.ESCALATED
    ):
        raise WorkerOrderStateError(f"Cannot complete a work order in state {order.status}.")
    previous = await _record_activity(
        db,
        order,
        worker,
        "COMPLETE_WORK",
        note=notes,
        latitude=latitude,
        longitude=longitude,
        geo_denied=geo_denied,
        client_ref=client_ref,
    )
    if previous is not None:
        changed = order.status != WorkOrderStatus.COMPLETED
        from_status = order.status
        order.status = WorkOrderStatus.COMPLETED
        order.completed_at = _now()
        if notes:
            order.worker_notes = notes
        db.add(
            WorkOrderStatusHistory(
                work_order_id=order.id,
                action=WorkOrderAction.COMPLETE_WORK.value,
                from_status=from_status,
                to_status=WorkOrderStatus.COMPLETED,
                actor_id=user.id,
                note=notes or "Work completed by field worker.",
            )
        )
        if changed and order.complaint is not None:
            if order.complaint.status.value != ComplaintStatus.RESOLVED.value:
                order.complaint.status = ComplaintStatus.RESOLVED
                db.add(
                    record_status_transition(
                        order.complaint,
                        ComplaintStatus.RESOLVED,
                        actor_id=user.id,
                        note="Field work completed.",
                    )
                )
            await _notify_work_completed(db, order.complaint, order)
        await db.commit()
    return await get_order_detail(db, user, order_id)


# --------------------------------------------------------------------------- #
# Photos (before / after evidence)
# --------------------------------------------------------------------------- #
def _validate_photo(content_type_raw: str | None, data: bytes, settings) -> tuple[str, str]:
    media_type = _classify_content_type(content_type_raw or "")
    if media_type is None:
        raise MediaValidationError("Unsupported file type. Upload an image.")
    if media_type.value == "VIDEO":
        content_types = _split_allowed(settings.ALLOWED_VIDEO_TYPES)
        if (content_type_raw or "").lower() not in content_types:
            raise MediaValidationError("Unsupported video type.")
        _validate_video((content_type_raw or "").lower(), data, settings.MAX_VIDEO_MB)
        return "VIDEO", (content_type_raw or "").lower()
    content_types = _split_allowed(settings.ALLOWED_IMAGE_TYPES)
    if (content_type_raw or "").lower() not in content_types:
        raise MediaValidationError("Unsupported image type.")
    _validate_image((content_type_raw or "").lower(), data, settings.MAX_IMAGE_MB)
    return "IMAGE", (content_type_raw or "").lower()


async def upload_photo(
    db: AsyncSession,
    user: User,
    order_id: uuid.UUID,
    *,
    category: str,
    content_type_raw: str | None,
    original_filename: str,
    data: bytes,
    latitude: float | None = None,
    longitude: float | None = None,
    geo_denied: bool = False,
    client_ref: str | None = None,
) -> WorkerOrderDetailOut:
    """Record a before/after evidence photo for a job (idempotent via client_ref)."""
    worker = await _require_profile(db, user)
    order = await _require_my_order(db, order_id, worker)
    category_upper = category.upper()
    if category_upper not in ("BEFORE", "AFTER"):
        raise MediaValidationError("category must be BEFORE or AFTER.")
    settings = get_settings()
    media_type, content_type = _validate_photo(content_type_raw, data, settings)

    # Idempotency: an already-synced photo upload returns the current state.
    if client_ref:
        existing_activity = await db.scalar(
            select(WorkOrderActivity).where(
                WorkOrderActivity.worker_id == worker.id,
                WorkOrderActivity.client_ref == client_ref,
            )
        )
        if existing_activity is not None:
            return await get_order_detail(db, user, order_id)

    storage = get_storage(settings)
    ext = _extension_for(content_type)
    key = f"work-orders/{order.id}/{category_upper.lower()}-{uuid.uuid4().hex}.{ext}"
    storage.upload(key, data, content_type)

    photo = WorkOrderPhoto(
        work_order_id=order.id,
        worker_id=worker.id,
        category=category_upper,
        original_filename=original_filename[:255],
        storage_key=key,
        storage_backend=getattr(storage, "backend_name", settings.STORAGE_BACKEND) or "local",
        content_type=content_type,
        size_bytes=len(data),
        allowed=True,
    )
    db.add(photo)
    await db.flush()
    db.add(
        WorkOrderActivity(
            work_order_id=order.id,
            worker_id=worker.id,
            activity_type="PHOTO_BEFORE" if category_upper == "BEFORE" else "PHOTO_AFTER",
            note=None,
            latitude=latitude,
            longitude=longitude,
            geo_denied=geo_denied,
            media_id=photo.id,
            client_ref=client_ref,
        )
    )
    await db.commit()
    return await get_order_detail(db, user, order_id)


__all__ = [
    "MediaValidationError",
    "WorkerOrderNotFoundError",
    "WorkerOrderStateError",
    "WorkerProfileError",
    "accept_job",
    "check_in",
    "complete_job",
    "get_dashboard",
    "get_order_detail",
    "save_notes",
    "start_job",
    "upload_photo",
]
