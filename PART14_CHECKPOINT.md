# Part 14 Checkpoint Report — Autonomous Dispatch & Work Orders

## Status: READY FOR NEXT PROMPT — YES

## What Was Implemented

**Deterministic worker-selection engine (`app/services/dispatch_engine.py`)** — given a
complaint's department, priority, required skills/equipment and a location, it scores every
eligible **FieldWorker** purely on five weighted criteria and never picks randomly:

- **Availability** (`availability`) — worker marked ACTIVE and not at their
  `max_active_orders` (active = `WorkerAssignment` rows with status `ASSIGNED`/`REASSIGNED`;
  `max_active_orders` defaults to `DISPATCH_MAX_ACTIVE_ORDERS`, e.g. 3).
- **Skill** (`skill`) — match of the worker's skills against `required_skills`.
- **Distance** (`distance`) — haversine from the worker's `home_lat`/`home_lon` to the
  complaint location (`DISPATCH_NORMALIZED_DISTANCE_METERS`), normalized to a 0..1 score.
- **Workload** (`workload`) — inverse of current active-order count.
- **Equipment** (`equipment`) — match of the worker's equipment against `required_equipment`.

Each candidate returns a transparent `CandidateScoreOut` breakdown (`score`, all five
sub-scores, `reasons`) so the outcome is explainable and auditable. When no worker qualifies
it returns an empty candidate list plus a human-readable `no_worker_reason` instead of
guessing.

**Honest ETA abstraction (`app/services/eta_service.py`)** — ETA is never presented as a live
route prediction when no routing provider is connected. `eta_source` is explicitly `"live"`
(when a real routing/OSRM provider is configured and returns a trace) **or** `"estimated"` (a
clearly-labeled distance-based heuristic); the frontend renders the source alongside the
value. This replaces the old no-op `get_eta` stub and documents the degradation fallback.

**Dispatch Agent (`app/agents/dispatch_agent.py`)** — LangGraph `START → compute → persist →
END`, `AGENT_NAME="dispatch"`, no LLM. It:
- loads the complaint's latest **routing** result (or falls back to a category→department
  map: GARBAGE→WASTE, FLOODING→DRAINAGE, PUBLIC_SAFETY→EMERGENCY_DISASTER, etc.) and
  priority context;
- runs the engine to deterministically pick a worker and compute a real ETA;
- persists a **draft work order** (`WorkOrderStatus.PENDING_APPROVAL`) with the department,
  priority, SLA, address, recommended action, ETA and (when one was chosen) `worker_id`;
- records a `WorkOrderStatusHistoryEntry` `DISPATCH` action;
- returns `{"work_order_id": ..., "output": ...}` via `_persist_node` (LangGraph does not
  mutate the caller's state dict in place, so the runner reads the final graph state from
  `ainvoke`'s return value).

The runner (`DispatchRunner.run`) uses `final_state = await self._graph.ainvoke(state)` and
derives `work_order_id` + `DispatchOutput` from that final state, persisting the
`agent="dispatch"` run record.

**Models + migration** — new `FieldWorker` (extends the existing worker model with
`user_id` + `department_id` requirements, `skills`/`equipment` JSON, `home_lat`/`home_lon`,
`is_active`/`max_active_orders`), `WorkOrder`, `WorkOrderStatusHistory` and
`WorkerAssignment`; `WorkOrder`/`WorkerAssignment`/`WorkOrderStatusHistory` status columns
are `String` columns typed as `enum.StrEnum` (DB returns plain strings on read — `.value` is
only valid on writes). Enum additions in `app/models/enums.py`: `WorkOrderStatus`,
`AssignmentStatus`, `WorkOrderAction`. All four models registered in `app/models/__init__.py`.
Migration **`c685cc39bb71`** ("work_orders_status_history_worker_assignment_field_worker"),
applied to the live dev DB and verified; `alembic heads = current = c685cc39bb71`.

**Schemas (`app/schemas/work_order.py`)** — `CandidateScoreOut`, `DispatchInputs`,
`DispatchOutput`, `DispatchRecommendation`, `DispatchRunOut`, `DispatchRunIn`,
`DispatchRunResponse`, `WorkOrderDetailOut`, `WorkOrderListOut`, `WorkOrderStatusHistoryEntry`,
`WorkOrderStatusHistoryOut`, `WorkerAssignmentOut`, `WorkOrderAssignIn`, `WorkOrderActionIn`,
`WorkOrderEscalateIn`, `WorkOrderDetailBundle`.

**Service (`app/services/work_order_service.py`)** — Part 14 facade:
- `dispatch_work_order`, `get_dispatch_result`, `list_work_orders` (by complaint),
  `get_work_order` (detail + assignments + history), `get_work_order_history`.
- Officer actions — **`approve_work_order`** (draft `PENDING_APPROVAL` → `ASSIGNED`, creates
  the explicit `ASSIGNED` `WorkerAssignment` for the recommended worker), **`assign_work_order`**,
  **`reassign_work_order`** (supersedes the active assignment to `UNASSIGNED` and creates a
  `REASSIGNED` one), **`escalate_work_order`** (reason required), **`reject_work_order`** (note).
- Every action is written to the append-only `WorkOrderStatusHistory` audit trail with actor
  name + note + timestamp.
- **Access enforcement** via `user_can_view` (OWNER/officer/admin/ward-rep/field-worker see it;
  citizens only their own; ward-reps only their ward's). `WorkOrderStateError` for invalid
  transitions (e.g. approving a `REJECTED` order). Eager-loads `WorkOrder.complaint`,
  `WorkerAssignment.worker.user`, `WorkerAssignment.assigned_by_user`, and
  `WorkOrderStatusHistory.actor`; calls `db.expire_all()` after commits before re-querying to
  avoid detached-relationship/`greenlet_spawn` errors.

**API (`app/api/v1/work_orders.py`)** — registered in `app/api/router.py` as both
`complaints_router` (prefix `/complaints`) and `work_orders_router` (prefix `/work-orders`), all
**10** routes verified in openapi (48 paths total):
`POST /complaints/{id}/dispatch` (201), `GET /complaints/{id}/dispatch-result`,
`GET /complaints/{id}/work-orders`, `GET /work-orders/{wid}`,
`POST /work-orders/{wid}/approve`, `POST /work-orders/{wid}/assign`,
`POST /work-orders/{wid}/reassign`, `POST /work-orders/{wid}/escalate`,
`POST /work-orders/{wid}/reject`, `GET /work-orders/{wid}/history`. Officer actions are
staff-gated (OFFICER/ADMIN/WARD_REPRESENTATIVE); `_work_order_error` maps 403/404/409/400.

**Frontend**
- `frontend/src/lib/citizen-api.ts`: Part 14 types (`WorkOrderStatus`, `WorkOrderAction`,
  `DispatchCandidate`, `DispatchRecommendation`, `DispatchOutput`, `DispatchRunResponse`,
  `DispatchRunDetail`, `WorkOrderDetail`, `WorkOrderListOut`, `WorkOrderStatusHistoryEntry`,
  `WorkOrderStatusHistoryOut`, `WorkerAssignment`, `WorkOrderDetailBundle`) and functions
  `runDispatch` / `fetchDispatchResult` / `fetchComplaintWorkOrders` / `fetchWorkOrderDetail` /
  `fetchWorkOrderHistory` / `approveWorkOrder` / `assignWorkOrder` / `reassignWorkOrder` /
  `escalateWorkOrder` / `rejectWorkOrder`.
- New `work-order-card.tsx` — **Work Order & Dispatch** card with loading/empty/error/success
  states. Shows the dispatch recommendation (recommended worker + department + ETA with honest
  source, SLA, recommended action, the append-only scored **candidate worker list**, and a
  no-worker banner), the active work order with a color-coded status badge, assigned worker,
  ETA, an **assignments** list and an append-only **status history** timeline. Staff
  (OFFICER/ADMIN/WARD_REPRESENTATIVE) get contextual actions gated by work-order status:
  **Dispatch / Re-dispatch**, **Approve**, **Reject**, **Assign**/**Reassign** (worker chosen
  from the scored candidates), **Escalate** — each in an inline form (toast feedback), wired
  into `complaint-detail-view.tsx` right after `RoutingCard`.

## Migration
`c685cc39bb71` ("work_orders_status_history_worker_assignment_field_worker"): creates
`field_workers`, `work_orders`, `work_order_status_history`, `worker_assignments` tables plus
FKs/relationships. **Applied** and verified on the live dev DB. `alembic heads =
c685cc39bb71` = `alembic current`.

## Tests & Results
- Backend: **`tests/test_dispatch.py` — 14/14 pass**:
  - **Engine determinism**: preferred candidate is never random; scoring favors high-skill /
    low-distance / low-workload workers; busy workers (real `WorkOrder` + `WorkerAssignment`
    `status="ASSIGNED"`) are excluded; `max_active_orders=0` falls back to the configured max.
  - **ETA honesty**: `eta_source` is `"estimated"` in the no-provider path (never claims
    `"live"`); an estimated value is produced from distance.
  - **Agent integration (live DB)**: `DispatchRunner.run` persists `agent="dispatch"`,
    `SUCCEEDED`, returns a `work_order_id`, and writes a `DISPATCH` status-history entry.
  - **API + RBAC**: 401 unauthenticated, 403 cross-owner / non-staff; 404 unknown complaint;
    dispatch → work order → list → detail → history; officer **approve → assign → reassign →
    escalate**; rejecting a draft then trying to approve → **409**.
  - **Work-order detail** returns the full bundle (work_order + assignments + status_history)
    and surfaces `worker_name` after assignment.
- Ruff: **clean on the entire backend** (`ruff check .`).
- Regression (storage/LLM-independent): `test_routing.py` (26), `test_health.py`+`test_context.py`
  +`test_priority.py` (56), `test_correlation_agent.py`+`test_citizen.py`+`test_auth.py` (35),
  `test_geo.py` + non-media `test_complaint_tracking.py` (26) — all passed. The remaining
  `test_complaint_tracking.py` / `test_complaints.py` **media** failures are solely the
  **pre-existing S3/MinIO outage**, unrelated to Part 14.
- Frontend: **`npm run lint` clean** (0 errors, 0 warnings), **`npx tsc --noEmit` clean**,
  **`npm run build` passes** (Next 16 / TS / Turbopack). Icons (`Wrench`, `UserCheck`,
  `UserCog`, `ArrowUpCircle`, `XCircle`, `History`, `Gauge`, `Clock`) confirmed in
  lucide-react.

## Live E2E (via HTTP against the running dev stack)
- Restarted the backend; `/api/v1/health` 200; `/openapi.json` serves all **48** paths incl.
  the **10** Part-14 routes.
- Seeded a citizen + officer; created a **GARBAGE** complaint at 17.4327, 78.3885.
- `POST /complaints/{id}/dispatch` → **201**, `work_order_id` returned, `status=SUCCEEDED`,
  result `recommendation.department=WASTE` with candidate scores.
- Citizen `POST /work-orders/{wid}/approve` → **403** (staff-gated).
- Officer `POST /work-orders/{wid}/approve` → work_order `status=ASSIGNED`.
- `GET /complaints/{id}/work-orders` → lists the work order; `GET /work-orders/{wid}/history`
  → `DISPATCH, APPROVE` audit entries.
- Negative paths: unauthenticated → 401; civilian action → 403; unknown work order → 404.
- Frontend detail pages render the new Work Order & Dispatch card; ESLint / TS / production
  build all clean.

## Errors Fixed During This Session
- `AgentRun` has **no** `created_by` column — the dispatch agent moved `created_by` into
  `DispatchState` (`created_by: uuid.UUID | None`) and passes it via the runner's initial
  state dict instead of the run.
- `_persist_node` now **returns** `{"work_order_id": ..., "output": ...}`; LangGraph does not
  mutate the caller's state in place, so the runner reads the final graph state from
  `ainvoke`'s return (`final_state.get("work_order_id")`).
- Work-order status columns are String-typed StrEnum: **`.value` is invalid on read-back**.
  `_load_workers` cracked to `str(a.status) in ("ASSIGNED", "REASSIGNED")`; `approve/assign/
  reassign/escalate/reject` error messages no longer call `order.status.value` (AttributeError
  on a plain string) — they use `order.status` directly.
- **Reassign (and any worker-name render) raised `DetachedInstanceError` / `greenlet_spawn`**
  because `WorkerAssignment.worker.user` and `FieldWorker.user` were not eagerly loaded →
  lazy relationship access on a detached session. Fix: eager-load
  `selectinload(WorkOrder.assignments).selectinload(WorkerAssignment.worker).selectinload(FieldWorker.user)`
  and `assigned_by_user` / `actor`, plus `db.expire_all()` after commits.
- `max_active_orders=0` is falsy and fell back to `DISPATCH_MAX_ACTIVE_ORDERS` — tests that need
  a genuinely busy worker create a real `WorkOrder` + `WorkerAssignment` (`status="ASSIGNED"`).
- Frontend: the detail-refresh effect referenced `activeOrder` instead of a scalar id (was a
  dependency-array warning) and imported `fetchWorkOrderDetail` via a dynamic `import()`; both
  cleaned up — static import + `activeOrderId` derived id, no eslint warning.

## Known Limitations / Remaining Issues
- Assign/reassign worker selection in the UI uses the **scored candidates** surfaced by the
  latest dispatch recommendation (there is no separate "list all field workers" endpoint in
  scope). Candidates is the deterministic pool the officer acts on.
- ETA is honest but `"estimated"` when no routing provider is configured (no false `"live"`).
  Hooking a real OSRM/OSRM provider flips it to `"live"` with no code change.
- Redis down and S3/MinIO outage are pre-existing/environmental and unrelated to Part 14.

## Security
- No secrets introduced or logged. The dispatch engine is fully deterministic — no LLM call,
  no external service needed, never random. Officer actions are restricted to
  OFFICER/ADMIN/WARD_REPRESENTATIVE (403 for civilians; 401 unauthenticated; 404 unknown).
  Reads enforce complaint ownership / ward scope. Reason/note are recorded on every action; the
  status-history audit trail is append-only with actor + timestamp. ETA source is disclosed
  honestly (`live` vs `estimated`), never fabricated.

## Regression Status
- Backend ruff: PASS | `test_dispatch.py` (14): PASS | `test_routing.py` (26): PASS |
  health+context+priority (56): PASS | correlation+citizen/auth (35): PASS | geo+tracking-non-media
  (26): PASS | Alembic head `c685cc39bb71`: PASS | Frontend lint: PASS | `tsc --noEmit`: PASS |
  Frontend build: PASS | Live E2E (dispatch → citizen 403 → officer approve → ASSIGNED → list
  → history): PASS.
