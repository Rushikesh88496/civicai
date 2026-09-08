"""Work Orders & Autonomous Dispatch API (Part 14).

Endpoints:
- POST   /complaints/{complaint_id}/dispatch           — run dispatch agent (staff or owner)
- GET    /complaints/{complaint_id}/dispatch-result     — latest dispatch agent run
- GET    /complaints/{complaint_id}/work-orders          — all work orders for a complaint
- GET    /work-orders/{work_order_id}                    — work-order detail bundle
- GET    /work-orders/{work_order_id}/history            — append-only status-history trail
- POST   /work-orders/{work_order_id}/approve            — officer approves draft → assigned
- POST   /work-orders/{work_order_id}/assign             — officer assigns a worker
- POST   /work-orders/{work_order_id}/reassign           — officer reassigns to another worker
- POST   /work-orders/{work_order_id}/escalate           — officer escalates
- POST   /work-orders/{work_order_id}/reject             — officer rejects draft
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.work_order import (
    DispatchRunOut,
    DispatchRunResponse,
    WorkOrderActionIn,
    WorkOrderAssignIn,
    WorkOrderDetailBundle,
    WorkOrderEscalateIn,
    WorkOrderListOut,
    WorkOrderStatusHistoryOut,
)
from app.services.audit_service import (
    ACTION_WORK_ORDER_APPROVE,
    ACTION_WORK_ORDER_ASSIGN,
    ACTION_WORK_ORDER_ESCALATE,
    ACTION_WORK_ORDER_REASSIGN,
    ACTION_WORK_ORDER_REJECT,
    record_audit,
)
from app.services.work_order_service import (
    WorkOrderAccessError,
    WorkOrderNotFoundError,
    WorkOrderStateError,
    approve_work_order,
    assign_work_order,
    dispatch_work_order,
    escalate_work_order,
    get_dispatch_result,
    get_work_order,
    get_work_order_history,
    list_work_orders,
    reassign_work_order,
    reject_work_order,
)

# --- Router: complaint-scoped dispatch + list endpoints -----------------------------------

complaints_router = APIRouter(
    prefix="/complaints",
    tags=["complaints", "work-orders"],
)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Complaint not found.")


def _dispatch_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkOrderNotFoundError):
        return _not_found()
    if isinstance(exc, WorkOrderAccessError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, WorkOrderStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@complaints_router.post(
    "/{complaint_id}/dispatch",
    response_model=DispatchRunResponse,
    status_code=status.HTTP_201_CREATED,
)
async def run_dispatch(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DispatchRunResponse:
    """Run the dispatch agent to produce a draft work order and a recommended worker."""
    try:
        return await dispatch_work_order(db, user, complaint_id)
    except Exception as exc:
        raise _dispatch_error(exc) from exc


@complaints_router.get(
    "/{complaint_id}/dispatch-result",
    response_model=DispatchRunOut | None,
)
async def get_dispatch(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DispatchRunOut | None:
    """Return the latest dispatch agent run for a complaint (if any)."""
    try:
        return await get_dispatch_result(db, user, complaint_id)
    except Exception as exc:
        raise _dispatch_error(exc) from exc


@complaints_router.get(
    "/{complaint_id}/work-orders",
    response_model=WorkOrderListOut,
)
async def list_work_orders_for_complaint(
    complaint_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderListOut:
    """Return all work orders for a complaint (newest first)."""
    try:
        return await list_work_orders(db, user, complaint_id)
    except Exception as exc:
        raise _dispatch_error(exc) from exc


# --- Router: work-order-scoped detail + action endpoints ----------------------------------

work_orders_router = APIRouter(
    prefix="/work-orders",
    tags=["work-orders"],
)

_STAFF_DEPS = [
    Depends(require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE))
]


def _work_order_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorkOrderNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, WorkOrderAccessError):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, WorkOrderStateError):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _audit_work_order_action(
    db: AsyncSession,
    *,
    user: User,
    request: Request,
    action: str,
    work_order_id: uuid.UUID,
    after: dict,
) -> None:
    await record_audit(
        db,
        actor_id=user.id,
        action=action,
        entity_type="work_order",
        entity_id=str(work_order_id),
        after=after,
        ip_address=_client_ip(request),
    )
    await db.commit()


@work_orders_router.get(
    "/{work_order_id}",
    response_model=WorkOrderDetailBundle,
)
async def get_work_order_detail(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderDetailBundle:
    """Return a work order's detail, assignments and status history."""
    try:
        return await get_work_order(db, user, work_order_id)
    except Exception as exc:
        raise _work_order_error(exc) from exc


@work_orders_router.get(
    "/{work_order_id}/history",
    response_model=WorkOrderStatusHistoryOut,
)
async def get_work_order_status_history(
    work_order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderStatusHistoryOut:
    """Return the append-only status-history trail for a work order (newest first)."""
    try:
        return await get_work_order_history(db, user, work_order_id)
    except Exception as exc:
        raise _work_order_error(exc) from exc


@work_orders_router.post(
    "/{work_order_id}/approve",
    response_model=WorkOrderDetailBundle,
    dependencies=_STAFF_DEPS,
)
async def approve(
    request: Request,
    work_order_id: uuid.UUID,
    payload: WorkOrderActionIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderDetailBundle:
    """Officer approves a draft work order → ASSIGNED.
    Creates an explicit worker assignment if one was recommended.
    """
    try:
        bundle = await approve_work_order(
            db, user, work_order_id, note=payload.note if payload else ""
        )
    except Exception as exc:
        raise _work_order_error(exc) from exc
    await _audit_work_order_action(
        db,
        user=user,
        request=request,
        action=ACTION_WORK_ORDER_APPROVE,
        work_order_id=work_order_id,
        after={"status": bundle.work_order.status.value},
    )
    return bundle


@work_orders_router.post(
    "/{work_order_id}/assign",
    response_model=WorkOrderDetailBundle,
    dependencies=_STAFF_DEPS,
)
async def assign(
    request: Request,
    work_order_id: uuid.UUID,
    payload: WorkOrderAssignIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderDetailBundle:
    """Officer assigns (or re-assigns) a work order to a specific worker."""
    try:
        bundle = await assign_work_order(
            db, user, work_order_id, worker_id=payload.worker_id, reason=payload.reason
        )
    except Exception as exc:
        raise _work_order_error(exc) from exc
    await _audit_work_order_action(
        db,
        user=user,
        request=request,
        action=ACTION_WORK_ORDER_ASSIGN,
        work_order_id=work_order_id,
        after={
            "status": bundle.work_order.status.value,
            "worker_id": str(payload.worker_id),
        },
    )
    return bundle


@work_orders_router.post(
    "/{work_order_id}/reassign",
    response_model=WorkOrderDetailBundle,
    dependencies=_STAFF_DEPS,
)
async def reassign(
    request: Request,
    work_order_id: uuid.UUID,
    payload: WorkOrderAssignIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderDetailBundle:
    """Officer reassigns a work order to a different worker (supersedes current assignment)."""
    try:
        bundle = await reassign_work_order(
            db, user, work_order_id, worker_id=payload.worker_id, reason=payload.reason
        )
    except Exception as exc:
        raise _work_order_error(exc) from exc
    await _audit_work_order_action(
        db,
        user=user,
        request=request,
        action=ACTION_WORK_ORDER_REASSIGN,
        work_order_id=work_order_id,
        after={
            "status": bundle.work_order.status.value,
            "worker_id": str(payload.worker_id),
        },
    )
    return bundle


@work_orders_router.post(
    "/{work_order_id}/escalate",
    response_model=WorkOrderDetailBundle,
    dependencies=_STAFF_DEPS,
)
async def escalate(
    request: Request,
    work_order_id: uuid.UUID,
    payload: WorkOrderEscalateIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderDetailBundle:
    """Officer escalates a work order (no suitable worker available or out of SLA)."""
    try:
        bundle = await escalate_work_order(db, user, work_order_id, reason=payload.reason)
    except Exception as exc:
        raise _work_order_error(exc) from exc
    await _audit_work_order_action(
        db,
        user=user,
        request=request,
        action=ACTION_WORK_ORDER_ESCALATE,
        work_order_id=work_order_id,
        after={"status": bundle.work_order.status.value, "reason": payload.reason},
    )
    return bundle


@work_orders_router.post(
    "/{work_order_id}/reject",
    response_model=WorkOrderDetailBundle,
    dependencies=_STAFF_DEPS,
)
async def reject(
    request: Request,
    work_order_id: uuid.UUID,
    payload: WorkOrderActionIn | None = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkOrderDetailBundle:
    """Officer rejects a draft work order (it should not proceed)."""
    try:
        bundle = await reject_work_order(
            db, user, work_order_id, note=payload.note if payload else ""
        )
    except Exception as exc:
        raise _work_order_error(exc) from exc
    await _audit_work_order_action(
        db,
        user=user,
        request=request,
        action=ACTION_WORK_ORDER_REJECT,
        work_order_id=work_order_id,
        after={"status": bundle.work_order.status.value},
    )
    return bundle
