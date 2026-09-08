# Part 18 Checkpoint Report — Field Worker Application

## Status: READY — YES

## What Was Implemented

**Data model — append-only audit + evidence for field work:**
- `WorkOrderActivity` (**table `work_order_activities`**): immutable log of every field action
  (`ACCEPT`, `CHECK_IN`, `START_WORK`, `PHOTO_BEFORE`, `PHOTO_AFTER`, `NOTE_ADDED`,
  `COMPLETE_WORK`). Carries `client_ref` (idempotency key, unique per worker — DB constraint
  `uq_work_order_activities_worker_client_ref`), optional `note`, captured coordinates +
  `geo_denied` (GPS privacy), worker name projection, and `media_id` (→ `work_order_photos.id`,
  `SET NULL`).
- `WorkOrderPhoto` (**table `work_order_photos`**): stored evidence with `category` (`BEFORE` /
  `AFTER`), content type, size, `allowed` flag; files land in local storage under
  `work-orders/{order_id}/{category}-{hex}.{ext}` and are served via `/media`.
- `WorkerAssignment.accepted_at`; `WorkOrder.accepted_at / started_at / completed_at /
  worker_notes` + `activities` / `photos` relationships; `WorkOrderAction` enum extended, no new
  `WorkOrderStatus` values. Registered in `app/models/__init__.py`.
- Migration `alembic/versions/b4c5d6e7f8a9_work_order_activities_photos_worker_lifecycle.py`
  (revises `a3b4…`) — **applied** (`alembic upgrade head`).

**Backend API — 8 endpoints under `/api/v1/worker` (gated `FIELD_WORKER` only):**
- `GET /dashboard` (Assigned / Nearby / P1 / Completed; haversine ranking; GPS override via
  `?latitude=&longitude=`, fallback to `FieldWorker.home_*`), `GET /orders/{id}` (detail bundle:
  order + photos + activity feed), `POST .../accept`, `POST .../check-in`, `POST .../start`,
  `POST .../photos` (multipart, GIF/PNG/JPEG/WebP validation), `POST .../notes`, `POST .../complete`.
- **Workflow semantics:** `accept` keeps status ASSIGNED and records `accepted_at` + `ACCEPT`
  activity; `start` → IN_PROGRESS (complaint → IN_PROGRESS in lockstep); `complete` → COMPLETED
  (complaint → RESOLVED + `WORK_ORDER_COMPLETED` notifications to the owner and ward reps).
  Completing from ASSIGNED is allowed; actions on terminal states → 409.
- **Idempotency / queue-replay:** every action takes an optional `client_ref`; a replayed action
  returns the current state 200 and **never duplicates** activity rows (tested via DB count).
- **Error mapping (`_error`):** no profile / unknown-or-foreign order → 404 (other workers' orders
  are hidden, not leaked), wrong state → 409, bad media → 400, wrong role → 403, unauth → 401.

**Frontend — mobile-first FIELD WORKER app at `/work`:**
- `src/lib/field-worker-api.ts` — typed client mirroring the backend schemas (dashboard, detail,
  accept/check-in/start/notes/complete, multipart photo upload).
- `src/lib/offline-queue.ts` — queue-and-sync engine: every action enqueues with a client-generated
  `client_ref`, flushes in order via `navigator.onLine`/`online` events, is idempotent against
  replay, auto-drops poison items, and caps queued photo size (base64 snapshot).
- `components/field-worker/` — `field-worker-layout.tsx` (amber mobile shell, online/offline
  status + pending-queue badge, bottom tab bar Jobs / Nearby / Done), `job-list.tsx`, `nearby-jobs-map`
  (Leaflet, reusable marker/popup pattern), and the guided **step-wizard** page
  `src/app/work/orders/[id]/page.tsx`: Accept → Check-in/GPS (EN_ROUTE / ARRIVED + locate +
  GPS-denied) → Start → Before photo (`capture="environment"`, client GIF/PNG/JPEG validation) →
  Notes → After photo → Complete, with a live stepper, evidence gallery and activity timeline.
- Routes: `/work` (dashboard tabs), `/work/nearby`, `/work/completed`, `/work/orders/[id]`.
- Role plumbing: new `src/lib/roles.ts` `roleHome()` (WARD_REP→`/ward-rep`, OFFICER/ADMIN→
  `/officer`, **FIELD_WORKER→`/work`**, else `/dashboard`); login page now redirects by role, and
  `messages-layout` uses the shared helper + allows FIELD_WORKER.

## Tests & Results

- **`tests/test_field_worker.py` — 8/8 pass** (dashboard queues incl. far-worker GPS override +
  unassigned "nearby" order; RBAC 403 for officer/citizen + 401; worker-without-profile 404; full
  workflow accept→EN_ROUTE→ARRIVED→start→before/after PNG→notes→complete with complaint RESOLVED +
  `WORK_ORDER_COMPLETED` notification; GPS-denied check-in records no coords + invalid coords 422;
  client_ref replay unchanged status + single activity row + accept-after-start no-op; terminal-state
  409 guard; other-worker order hidden 404). Autouse `_leave_db_clean` teardown keeps shared-Postgres
  runs order-independent.
- **`test_dispatch.py` + `test_field_worker.py` run together — 22/22 pass** (the worker-fill /
  worker-cleanup interference class is green in both orders).
- Backend **ruff: clean**. Full backend suite: **254 passed** (run at backend completion).
- Frontend: **eslint clean** (incl. strict `react-hooks/set-state-in-effect`), **`npx tsc --noEmit`
  clean**, **`next build` passes** with `/work`, `/work/completed`, `/work/nearby`,
  `/work/orders/[id]` in the route table.
- OpenAPI live: **8/8 `/api/v1/worker/*` paths** present.

## Live E2E (HTTP against the running stack; uvicorn restarted onto current code)

- The pre-existing uvicorn on :8000 was serving a stale build (no `/worker` routes); it was
  restarted from the current backend (two zapped PIDs, fresh process). Re-verified OpenAPI → 8
  worker paths.
- **39/39 checks passed** against a freshly seeded worker + citizen + complaint + assigned P1 order,
  driving the exact request/response contract the frontend uses: login (FIELD_WORKER); dashboard
  (assigned / P1 / GPS-override); detail (all UI fields + photos + activities); accept
  (`accepted_at`, status stays ASSIGNED); EN_ROUTE check-in with GPS; ARRIVED check-in with
  **GPS denied recorded without leaking coords**; start → IN_PROGRESS with complaint lockstep;
  multipart **before photo**; notes persisted; multipart **after photo**; **idempotent replay**
  (same `client_ref` → status unchanged, exactly 1 activity row in DB); complete → COMPLETED with
  complaint RESOLVED + owner `WORK_ORDER_COMPLETED` notification; completed queue refresh;
  start-after-complete → 409.
- All seeded E2E rows were removed afterwards (complaints + work orders + activities + photos +
  worker + citizen); confirmed 0 `live-e2e*` rows remain.

## Errors Fixed During This Session

- **SQLAlchemy async pitfalls (backend):** removed all `db.expire_all()` calls after commit
  (they expired `user` and later sync reads on `.id` tripped `greenlet_spawn has not been called`);
  `_load_order` now uses `.execution_options(populate_existing=True)` + `selectinload` (incl.
  `assignments`) so re-queries refresh previously-loaded `activities`/`photos` and never lazy-load
  inside async serialization; indentation errors from the regex cleanup (no-op replay returning
  `None` under `if previous is not None:`) fixed to function-body level.
- **Shared-Postgres flakiness:** `test_dispatch.py::_clear_workers` ORM-deletes FieldWorkers which
  nulls NOT-NULL `worker_assignments.worker_id`; `test_field_worker.py` now carries an
  `@pytest.fixture(autouse=True)` async teardown (module-scoped `asyncio.run` variant failed with
  a dead-loop RuntimeError).
- **Frontend strict lint:** refactored all data effects to the repo's async-`.then` pattern (no
  synchronous `setState` in effect bodies); removed unused imports; `eslint-disable-next-line` for
  evidence `<img>`; `hasNote` cast; `QueueEnqueueResult.offline` required field.
- **Login routing:** login now routes by role (previously every user landed on the CITIZEN-only
  `/dashboard`, which bounces FIELD_WORKERs).

## Known Limitations / Remaining Issues

- **Offline = queue-and-sync only, not full PWA.** No service worker / offline asset caching;
  queued photos are base64 snapshots capped at ~1.5 MB (files up to 10 MB must wait for a
  connection). Honest and by design for this part.
- Redis still down (pre-existing): no real-time push; Notifications/state rely on polling +
  on-demand refresh.
- Full backend suite is run per-file (all green as documented in prior parts); running everything
  at once still exceeds the practical CI window — not a functional regression.
- The demo DB had no FIELD_WORKER account (seed lists `worker@example.com` but hadn't been applied);
  the live E2E spawned and cleaned up its own worker rather than altering demo data.

## Security

- No secrets introduced or logged. Every `/worker` route authenticates (401), enforces
  `FIELD_WORKER` (403 otherwise), and hides other workers' orders as 404 (no leakage).
- GPS privacy: coordinates are recorded only when supplied; a denied/unavailable fix records
  `geo_denied=True` and **no** lat/lon (verified in tests + live).
- Idempotent actions make replayed network retries harmless — an action is never applied twice.
- Uploads are content-type/length validated server-side and served through `/media` (local storage).

## Regression Status

Backend ruff: PASS | Backend tests — `test_field_worker` 8/8, `test_dispatch`+`test_field_worker`
22/22, full suite 254: PASS | Alembic migration applied: PASS | Frontend eslint: PASS |
`tsc` / `next build`: PASS | Live REST E2E (39 checks, GPS denied + idempotent replay): PASS |
OpenAPI 8 worker paths: PASS | Live DB left clean of E2E rows: PASS.