# PART 32 — Human-in-the-Loop Assignment Workflow (AI Recommendation vs Official Assignment)

## Status

**COMPLETE — backend 449 passed, ruff clean; frontend lint/typecheck/build clean, 14 vitest green; dev DB at head `d6e7f8a9b0c3`.**

## What changed

**The core principle:** the Dispatch Agent only ever produces a *recommendation*. An official assignment exists only when a staff officer signs off — an AI recommendation is never presented as, nor stored as, a `worker_assignments` row.

### Backend

- **Migration** `d6e7f8a9b0c3_hitl_assignment_sources.py` (head: `31a2b3c4d5e6`):
  - `work_orders.recommended_worker_id` — the worker the dispatch agent picked, **frozen at draft time** (FK → field_workers `SET NULL`, indexed). Unlike `worker_id` it never mutates, so any later reassignment can still be classified against the original AI pick.
  - `worker_assignments.origin` (`String(32)`) — provenance of each official assignment.
- **`dispatch_agent.py::_persist_node`** now also stores `recommended_worker_id` on the draft (previously only `worker_id`).
- **`work_order_service.py`**:
  - Constants `ASSIGNMENT_ORIGIN_AI` / `ASSIGNMENT_ORIGIN_OVERRIDE` / `ASSIGNMENT_ORIGIN_MANUAL`.
  - `_assignment_origin(order, worker_id)` — classifies an officer's pick against the frozen recommendation.
  - `approve_work_order` writes the approval assignment with `origin=AI_RECOMMENDATION`.
  - `assign_work_order` / `reassign_work_order` set the origin and, when the pick **differs** from the recommendation, write a `human_overrides` row (`override_type="assignment"`, original/new worker names + ids, reason notes the AI pick).
  - `_load_work_order` eager-loads the recommendation so names render in the detail bundle.
- **`api/v1/work_orders.py`** — approve/assign/reassign audit `after` payloads now include: `complaint_id`, `work_order_id`, `previous_assignee_id/name`, `new_assignee_id/name`, `assigning_user_id`, `assignment_reason`, `assignment_source`, `is_ai_recommended`, `officer_decision` (`accepted` / `overridden` / `manual`), `status`. The "new" assignment is the last row (`assigned_at` ASC); the previous one is the penultimate.
- **`complaint_tracking_service.py`** — the complaint timeline now returns `work_order_events` (DISPATCH → APPROVE/ASSIGN/REASSIGN → worker ACCEPT/START_WORK/photo/COMPLETE_WORK → REOPEN/CLOSE) so the UI can render the full lifecycle in one request (`ComplaintTimelineOut.work_order_events`).
- **Schemas** — `WorkerAssignmentOut.origin`, `WorkOrderDetailOut.recommended_worker_id` / `recommended_worker_name`, new `WorkOrderTimelineEvent`.

### Tests — `tests/test_hitl_assignment.py` (9 new)

- Draft: `PENDING_APPROVAL`, `recommended_worker_id` frozen, **no** `WorkerAssignment` row.
- Approve ⇒ one assignment `origin=AI_RECOMMENDATION`, no override row.
- Assign same worker as recommendation ⇒ `AI_RECOMMENDATION`, `officer_decision=accepted`.
- Assign a different worker ⇒ `OFFICER_OVERRIDE` **and** a `human_overrides` row (original/new worker).
- Assign with no recommendation ⇒ `MANUAL`, no override.
- Reassign ⇒ both rows preserved (AI + override), `human_overrides` row, audit has previous/new assignee names+ids.
- Approve audit payload contains all Part 32 fields.
- Timeline returns `work_order_events` (DISPATCH, APPROVE).
- RBAC: citizen and field worker → 403 on approve; ward rep of **another ward** → 403/404; officer can approve.

### Frontend

- **`citizen-api.ts`** — types for `WorkerAssignment.origin`, `WorkOrderDetail.recommended_worker_id/name`, `ComplaintTimeline.work_order_events` + `WorkOrderTimelineEvent`.
- **`work-order-card.tsx`** — explicit **AI recommendation** (indigo, "frozen at dispatch time — an officer decision turns this into an official assignment") vs **Official assignment** (shows current assignee + `OriginBadge`) side-by-side panels; `OriginBadge` renders `AI recommendation accepted` / `Officer override` / `Manual assignment`; pending-draft banner for officers with **Accept AI recommendation** (approve) and **Choose another worker** (assign); origin badges on the assignments list.
- **`workflow-lifecycle-card.tsx`** (new) — merges complaint + work-order events into one 12-checkpoint lifecycle: submitted → triaged → routed → officer review → signed & assigned → accepted → in progress → evidence → AI verify → officer verify → resolved → closed, with timestamps/actors and a progress footer. Consumed in `complaint-detail-view.tsx` under the work-order card.

## Verifications

- Backend: `pytest` → **449 passed**; `ruff check app tests` clean.
- Frontend: `npm run lint`, `typecheck`, `build`, `test` (14) clean.
- Dev DB: `alembic heads` → `d6e7f8a9b0c3 (head)`; `upgrade head` applied.

## Notes / invariants preserved

- RBAC untouched: approve/assign/reassign/escalate/reject remain OFFICER/ADMIN/WARD_REPRESENTATIVE, ward-scoped (`_assert_can_view_work_order`).
- Existing behavior kept: a draft inherits `worker_id` = the recommended worker (projected until approved) — the *authoritative* marker of "official" remains a persisted `worker_assignments` row.
- A reassignment row's status is `REASSIGNED` (not `ASSIGNED`), so audit classification uses row order (`assigned_at`) rather than a status filter.

**READY FOR NEXT PROMPT: YES**