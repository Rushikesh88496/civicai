"""Field Worker Application API (Part 18).

Endpoints (mobile-first, gated to FIELD_WORKER role):
- GET  /worker/dashboard                    — assigned / nearby / P1 / completed queues
- GET  /worker/orders/{order_id}            — full job detail bundle (sync payload)
- POST /worker/orders/{order_id}/accept     — accept the assignment
- POST /worker/orders/{order_id}/check-in   — GPS check-in (EN_ROUTE / ARRIVED)
- POST /worker/orders/{order_id}/start      — start work → IN_PROGRESS
- POST /worker/orders/{order_id}/notes      — save free-text field notes
- POST /worker/orders/{order_id}/photos     — upload a before/after evidence photo
- POST /worker/orders/{order_id}/finish     — finish work → WORK_COMPLETED (no complaint resolve)
- POST /worker/orders/{order_id}/submit-evidence — submit resolution evidence → EVIDENCE_SUBMITTED
- POST /worker/orders/{order_id}/start-rework — restart a RETURNED_FOR_REWORK job → IN_PROGRESS

The worker never resolves the complaint: resolution is confirmed by the AI
resolution verification stage once the evidence is submitted. Every action
accepts an optional ``client_ref`` so the offline sync engine can replay a
queued action idempotently (a replayed action returns the same state rather
than creating a duplicate).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.field_worker import (
    WorkerAcceptIn,
    WorkerCheckInIn,
    WorkerDashboardOut,
    WorkerFinishIn,
    WorkerNotesIn,
    WorkerOrderDetailOut,
    WorkerProfileOut,
    WorkerReworkIn,
    WorkerStartIn,
    WorkerSubmitEvidenceIn,
)
from app.services import field_worker_service as svc

router = APIRouter(
    prefix="/worker",
    tags=["worker"],
    dependencies=[Depends(require_roles(RoleName.FIELD_WORKER.value))],
)


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, (svc.WorkerOrderNotFoundError, svc.WorkerProfileError)):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, svc.WorkerOrderStateError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    if isinstance(exc, svc.EvidenceRequiredError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))
    if isinstance(exc, svc.MediaValidationError):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))


@router.get("/dashboard", response_model=WorkerDashboardOut)
async def dashboard(
    latitude: float | None = Query(default=None, ge=-90, le=90),
    longitude: float | None = Query(default=None, ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerDashboardOut:
    try:
        return await svc.get_dashboard(db, user, ref_lat=latitude, ref_lon=longitude)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.get("/me", response_model=WorkerProfileOut)
async def worker_profile(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerProfileOut:
    try:
        return await svc.get_worker_profile(db, user)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.get("/orders/{order_id}", response_model=WorkerOrderDetailOut)
async def order_detail(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        return await svc.get_order_detail(db, user, order_id)
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/accept", response_model=WorkerOrderDetailOut)
async def accept(
    order_id: uuid.UUID,
    payload: WorkerAcceptIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        p = payload or WorkerAcceptIn()
        return await svc.accept_job(
            db,
            user,
            order_id,
            note=p.note,
            latitude=p.latitude,
            longitude=p.longitude,
            geo_denied=p.geo_denied,
            client_ref=p.client_ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/check-in", response_model=WorkerOrderDetailOut)
async def check_in(
    order_id: uuid.UUID,
    payload: WorkerCheckInIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        return await svc.check_in(
            db,
            user,
            order_id,
            activity_type=payload.activity_type,
            latitude=payload.latitude,
            longitude=payload.longitude,
            accuracy_m=payload.accuracy_m,
            geo_denied=payload.geo_denied,
            note=payload.note,
            client_ref=payload.client_ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/start", response_model=WorkerOrderDetailOut)
async def start(
    order_id: uuid.UUID,
    payload: WorkerStartIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        p = payload or WorkerStartIn()
        return await svc.start_job(
            db,
            user,
            order_id,
            note=p.note,
            latitude=p.latitude,
            longitude=p.longitude,
            geo_denied=p.geo_denied,
            client_ref=p.client_ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/notes", response_model=WorkerOrderDetailOut)
async def notes(
    order_id: uuid.UUID,
    payload: WorkerNotesIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        return await svc.save_notes(
            db, user, order_id, notes=payload.notes, client_ref=payload.client_ref
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/photos", response_model=WorkerOrderDetailOut)
async def upload_photo(
    order_id: uuid.UUID,
    category: str = Form(...),
    file: UploadFile = File(...),
    latitude: float | None = Form(default=None),
    longitude: float | None = Form(default=None),
    geo_denied: bool = Form(default=False),
    client_ref: str | None = Form(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    data = await file.read()
    try:
        return await svc.upload_photo(
            db,
            user,
            order_id,
            category=category,
            content_type_raw=file.content_type,
            original_filename=file.filename or "photo",
            data=data,
            latitude=latitude,
            longitude=longitude,
            geo_denied=geo_denied,
            client_ref=client_ref,
        )
    except svc.MediaValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - storage/network failures surface as a clean 500
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Upload storage is unavailable."
        ) from exc


@router.post("/orders/{order_id}/finish", response_model=WorkerOrderDetailOut)
async def finish(
    order_id: uuid.UUID,
    payload: WorkerFinishIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        p = payload or WorkerFinishIn()
        return await svc.finish_job(
            db,
            user,
            order_id,
            notes=p.notes,
            latitude=p.latitude,
            longitude=p.longitude,
            geo_denied=p.geo_denied,
            client_ref=p.client_ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/submit-evidence", response_model=WorkerOrderDetailOut)
async def submit_evidence(
    order_id: uuid.UUID,
    payload: WorkerSubmitEvidenceIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        p = payload or WorkerSubmitEvidenceIn()
        return await svc.submit_evidence(
            db,
            user,
            order_id,
            notes=p.notes,
            latitude=p.latitude,
            longitude=p.longitude,
            geo_denied=p.geo_denied,
            client_ref=p.client_ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc


@router.post("/orders/{order_id}/start-rework", response_model=WorkerOrderDetailOut)
async def start_rework(
    order_id: uuid.UUID,
    payload: WorkerReworkIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkerOrderDetailOut:
    try:
        p = payload or WorkerReworkIn()
        return await svc.start_rework(
            db,
            user,
            order_id,
            note=p.note,
            latitude=p.latitude,
            longitude=p.longitude,
            geo_denied=p.geo_denied,
            client_ref=p.client_ref,
        )
    except Exception as exc:  # noqa: BLE001
        raise _error(exc) from exc
