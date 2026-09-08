"""SLA Monitoring API (Part 20).

Staff-only endpoints that power the officer-facing SLA monitor:

- GET    /sla/orders           — live board (state/progress/countdown per order)
- POST   /sla/run              — trigger the monitoring agent (optional filters)
- GET    /sla/run              — the most recent persisted monitoring run
- GET    /sla/policies         — list the configurable rulebook
- POST   /sla/policies         — add a rule
- PUT    /sla/policies/{id}    — update a rule
- DELETE /sla/policies/{id}    — remove a rule

Access mirrors the command center: OFFICER / ADMIN / WARD_REPRESENTATIVE.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.sla_agent import SlaAgent
from app.api.deps import require_roles
from app.db.session import get_db
from app.models import User
from app.models.enums import RoleName
from app.schemas.sla import (
    SlaOrdersPage,
    SlaPolicyIn,
    SlaPolicyOut,
    SlaRunOut,
    SlaRunResponse,
    SlaScanOutput,
)
from app.services import sla_policy_service, sla_service

router = APIRouter(prefix="/sla", tags=["sla"])


def _require_staff(user: User) -> User:
    if user.role.name not in (
        RoleName.OFFICER.value,
        RoleName.ADMIN.value,
        RoleName.WARD_REPRESENTATIVE.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to access the SLA monitor.",
        )
    return user


def _policy_error(exc: Exception) -> HTTPException:
    if isinstance(exc, sla_policy_service.SlaPolicyNotFoundError):
        return HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    if isinstance(exc, sla_policy_service.SlaPolicyValidationError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))


@router.get("/orders", response_model=SlaOrdersPage)
async def get_sla_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    state: str | None = Query(None, description="ON_TRACK|AT_RISK|BREACHED|COMPLETED"),
    department: str | None = None,
    priority: str | None = None,
    search: str | None = None,
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> SlaOrdersPage:
    _require_staff(user)
    items, counts, total = await sla_service.list_sla_orders(
        db,
        page=page,
        page_size=page_size,
        state=state,
        department=department,
        priority=priority,
        search=search,
    )
    return SlaOrdersPage(items=items, counts=counts, total=total, page=page, page_size=page_size)


@router.post("/run", response_model=SlaRunResponse)
async def run_sla_agent(
    department: str | None = Query(None, description="Restrict the scan to one department"),
    priority: str | None = Query(None, description="Restrict the scan to one priority bucket"),
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> SlaRunResponse:
    _require_staff(user)
    run = await SlaAgent().run(db, department=department, priority=priority)
    result = (
        SlaScanOutput.model_validate(run.structured_result)
        if run.structured_result is not None
        else None
    )
    return SlaRunResponse(
        run_id=run.id,
        status=run.status.value if hasattr(run.status, "value") else str(run.status),
        result=result,
        error=run.error,
        retry_allowed=True,
    )


@router.get("/run", response_model=SlaRunOut | None)
async def get_latest_sla_run(
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> SlaRunOut | None:
    _require_staff(user)
    return await sla_service.latest_run(db)


@router.get("/policies", response_model=list[SlaPolicyOut])
async def list_policies(
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> list[SlaPolicyOut]:
    _require_staff(user)
    rows = await sla_policy_service.list_policies(db)
    return [SlaPolicyOut.model_validate(r) for r in rows]


@router.post("/policies", response_model=SlaPolicyOut, status_code=status.HTTP_201_CREATED)
async def create_policy(
    payload: SlaPolicyIn,
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> SlaPolicyOut:
    _require_staff(user)
    try:
        rule = await sla_policy_service.create_policy(
            db,
            name=payload.name,
            priority=payload.priority.value if payload.priority else None,
            department=payload.department.value if payload.department else None,
            category=payload.category.value if payload.category else None,
            sla_hours=payload.sla_hours,
            at_risk_percent=payload.at_risk_percent,
            escalate_on_breach=payload.escalate_on_breach,
            active=payload.active,
            actor_id=user.id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _policy_error(exc) from exc
    return SlaPolicyOut.model_validate(rule)


@router.put("/policies/{policy_id}", response_model=SlaPolicyOut)
async def update_policy(
    policy_id: uuid.UUID,
    payload: SlaPolicyIn,
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> SlaPolicyOut:
    _require_staff(user)
    try:
        rule = await sla_policy_service.update_policy(
            db,
            policy_id,
            name=payload.name,
            priority=payload.priority.value if payload.priority else None,
            department=payload.department.value if payload.department else None,
            category=payload.category.value if payload.category else None,
            sla_hours=payload.sla_hours,
            at_risk_percent=payload.at_risk_percent,
            escalate_on_breach=payload.escalate_on_breach,
            active=payload.active,
            actor_id=user.id,
        )
    except Exception as exc:  # noqa: BLE001
        raise _policy_error(exc) from exc
    return SlaPolicyOut.model_validate(rule)


@router.delete("/policies/{policy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_policy(
    policy_id: uuid.UUID,
    user: User = Depends(
        require_roles(RoleName.OFFICER, RoleName.ADMIN, RoleName.WARD_REPRESENTATIVE)
    ),
    db: AsyncSession = Depends(get_db),
) -> None:
    _require_staff(user)
    try:
        await sla_policy_service.delete_policy(db, policy_id)
    except Exception as exc:  # noqa: BLE001
        raise _policy_error(exc) from exc
