# Part 16 Checkpoint Report — Ward Representative Portal

## Status: READY — YES

## What Was Implemented

**Data model — authorized citizen conversations (`app/models/complaint_thread_message.py`)**:
- `ComplaintThreadMessage` (complaint_id, author_id, role, body, created_at) with relations
  `Complaint.thread_messages` and `User.author` (back_populates). Exported via
  `app/models/__init__.py`.
- Migration `alembic/versions/d6e7f8a9b0c1_complaint_thread_messages.py` (revises
  `c685cc39bb71`) — **applied**; table verified (columns id/complaint_id/author_id/role/
  body/created_at).
- Conversation participation is authorized: a representative may only read/write the thread of
  complaints **in their own ward**; citizens may only access threads they own.

**Backend service (`app/services/ward_rep_service.py`)** — a ward-scoped facade (Part 16) with
eight endpoints behind `require_roles(WARD_REPRESENTATIVE, OFFICER, ADMIN)`:

- **Dashboard** (`GET /dashboard`) — ward identity (code/name/description), the ward's
  representative, and KPIs: total / open / resolved (status-bucket aware), **critical** (latest
  dynamic-priority bucket == P1_CRITICAL), and **SLA breaches** (open work orders whose `due_at`
  has passed). All counts are scoped to `Complaint.ward_id == user.ward_id`.
- **Map** (`GET /map`) — the ward's complaints (title/id/status/latest dynamic priority/
  department/category/lat/lon/created) **coloured by dynamic priority** plus the ward's work
  orders as squares. Uses the same correlated `_latest_priority_priority()` /
  `_latest_department_subq()` (override-wins) helpers as Part 15 but ward-scoped.
- **AI ward summary** (`GET /summary`) — **Groq-powered** when `GROQ_API_KEY` is configured
  (live mode), otherwise a **deterministic synthesized fallback** grounded only in real records
  (never hallucinated counts). `WardSummaryOut.generated_by` exposes `"groq"` / `"synthesized"`.
  Service injects `ai: AIService | None` so tests can force the deterministic path.
- **Actions** — `POST /complaints/{id}/send-update` (append a rep message to the authorized
  conversation thread; returns the updated conversation), `POST /complaints/{id}/escalate`
  (status → ESCALATED with a `record_status_transition` history row + guard against
  doubly-escalated complaints), `GET /complaints/{id}/work-order` (200 with order or 200 null),
  `GET /complaints/{id}/cluster` (correlation members incl. similarity/distance/status).
- Every read/write route validates the complaint exists and is viewable via
  `complaint_tracking_service.user_can_view` → `ComplaintNotFoundError` → 404,
  `ComplaintAccessError` → 403, `ValueError` → 400.

**API (`app/api/v1/ward_rep.py`)** — registered in `app/api/router.py` under `/api/v1/ward-rep`.
8 new paths (53 → **61** in openapi).

**Frontend — `/ward-rep` route group** (WARD_REPRESENTATIVE / OFFICER / ADMIN allowed):
- `frontend/src/lib/ward-rep-api.ts` — typed client (mirrors `officer-api.ts`'s
  `authorizedJson`) + 8 API functions + all Part-16 types.
- `ward-map.tsx` (dynamic + SSR-off loading) / `ward-map-canvas.tsx` (Leaflet: priority-coloured
  dots with my own `escapeHtml`, blue rotated-square work-order icons).
- `ward-rep-layout.tsx` + `src/app/ward-rep/layout.tsx` + `page.tsx` — `ProtectedRoute` gated to
  `["WARD_REPRESENTATIVE","OFFICER","ADMIN"]`.
- `ward-portal.tsx` — header (ward + rep), **5 KPI cards**, **AI ward summary panel** (live vs
  synthesized badge via `generated_by`; highlights + recommended actions for synthesized mode),
  Leaflet map, complaint list with per-row actions (View incident / Chat / Work Order / Cluster /
  Escalate) driving `Modal`-based detail, conversation (message bubbles + send), work-order,
  cluster, and escalation-reason modals; toasts via `useToast`; loading/empty/error states.

## Tests & Results

- **`tests/test_ward_rep.py` — 13/13 pass**, covering:
  - auth (401), citizen forbidden on all endpoints (403), officer+admin allowed.
  - `test_dashboard_scoped_to_own_ward` (cross-ward isolation), `test_dashboard_sla_breach_in_ward`.
  - `test_empty_ward_dashboard_and_map` (empty ward → zero KPIs / no markers).
  - `test_large_dataset_aggregation` (bulk with many statuses/priorities → correct open/resolved/
    critical counts).
  - `test_map_returns_ward_complaints_with_priority` (latest dynamic priority + dept).
  - `test_ward_summary_endpoint` (live) + `test_ward_summary_synthesized_without_groq` /
    `..._when_groq_unavailable` (deterministic fallback grounded in real records).
  - `test_conversation_send_and_read_scoped` (authorized conversation + cross-ward denial).
  - `test_escalation_request_and_state_guard` (escalate + double-escalate guard).
  - `test_work_order_view_and_cluster` (work order payload + cluster members).
- Ruff: **clean** on `seed.py`, Part-16 app files, and `tests/`.
- Regression: `test_command_center` + `test_routing` **36/36**; `test_dispatch` + `test_citizen`
  + `test_complaint_tracking` **22 pass** — the only 4 failures are the **pre-existing**
  S3/MinIO media-upload outage (`Upload storage is unavailable.` → 500), unrelated to Part 16.
- Frontend: **`npx eslint` clean** (0 errors incl. the strict `react-hooks/set-state-in-effect`
  rule), `npx tsc` via **`npx next build`** passes; `/ward-rep` listed in the build output.

## Live E2E (HTTP against the running stack)

- Restarted uvicorn (PID 20724); `/openapi.json` serves (now ≥61 paths incl. the 8
  `/api/v1/ward-rep/*` routes).
- **Seed fix (this session):** `seed.py` never set `user.ward_id` for WARD_REPRESENTATIVE seeds
  (only created the `WardRepresentative` row), so the live demo reps resolved no ward — while
  every ward-scoping service (tracking, command center, ward-rep) keys off `user.ward_id`.
  Fixed `_seed_user` to set `user.ward_id = ward.id` for reps, and patched the existing
  `rep@example.com` → W-001 and `rep2@example.com` → W-002 rows.
- `GET /ward-rep/dashboard` (rep) → **200**, ward `{code:"W-001", name:"Downtown"}`,
  representative "Ward Rep".
- `GET /ward-rep/map` (rep2, W-002) → **200**, **7 complaints, 0 work orders**.
- `GET /ward-rep/summary` (rep2) → **200, `generated_by: "groq"`** (live Groq key configured),
  `complaint_count: 7`.
- `GET /complaints/{id}/conversation` → **200** (0 messages) → `POST /send-update` → **200**,
  1 message, body round-tripped → `GET` again confirms the message persisted.
- `POST /complaints/{id}/escalate` → **200**, `{"status":"ESCALATED","note":"…"}`.
- `GET /complaints/{id}/work-order` → **200 null** (no order exists) — matches the contract.
- `GET /complaints/{id}/cluster` → **200**, `members: []`.
- **RBAC / scoping:** rep of W-001 reading a W-002 complaint conversation → **403**
  (cross-ward denied); citizen on `/dashboard`, `/map`, `/summary` → **403** each;
  unauthenticated → **401** (covered by tests).

## Errors Fixed During This Session

- **Seed gap (live demo):** reps had no `user.ward_id` → portal showed `ward: null` /
  "No ward assigned." Fixed in `seed.py` (fresh installs) + patched the live rows.
- **E2E script:** login token is at `body["tokens"]["access_token"]`; cp1252 console choked on a
  Groq summary's non-breaking hyphen (script-only, fixed with UTF-8 stdout).
- **Frontend lint/type errors** while building `ward-portal.tsx`: unescaped apostrophe
  (→ `&apos;`), unused `addToast`/`defaultModalState`, missing `"escalate"` in the modal-type
  union, and the `react-hooks/set-state-in-effect` flag on the three data modals — fixed by
  keying the modals per complaint (clean remount + initial `loading=true`) instead of
  `setLoading(true)` in the effect body.

## Known Limitations / Remaining Issues

- S3/MinIO outage (pre-existing) blocks the media-upload tests only; unrelated to Part 16.
- Redis down: realtime degrades gracefully (30s portal poll + manual Refresh); the ward-rep
  portal is on-demand REST (not WS) so it is unaffected.
- Repeating the live escalation E2E on the **same** complaint will hit the double-escalate
  state guard (by design); the first run persists a demo escalation + one rep message in W-002
  (visible in `rep2@example.com`'s portal).
- W-001 (`rep@example.com`) has no seeded complaints of its own (all seed complaints belong to
  W-002's citizen) — its portal shows a healthy zero-state; `rep2@example.com` (W-002) demos the
  full data view.
- Full backend test suite still times out when run all-at-once (~15 min); suites are run in
  isolation (as documented in prior parts).

## Security

- No secrets introduced or logged. Ward-rep reads/writes are gated to
  WARD_REPRESENTATIVE / OFFICER / ADMIN (unauthenticated 401, citizen 403) and **scoped to the
  representative's own ward** (cross-ward read → 403/404). Escalation and thread writes go through
  `record_status_transition` + authorized conversation checks; roles permitted in the thread are
  explicit (`CITIZEN`, `WARD_REPRESENTATIVE`, `OFFICER`, `ADMIN`).

## Regression Status

- Backend ruff: PASS | `test_ward_rep.py` (13): PASS | `test_command_center` + `test_routing`
  (36): PASS | `test_dispatch` + `test_citizen` + `test_complaint_tracking` (22 pass; 4 are the
  pre-existing S3 media failures): PASS | Frontend eslint: PASS | `tsc`/`next build`: PASS |
  Live REST E2E (all 8 routes incl. Groq summary, escalation, conversation, citizen 403,
  cross-ward 403): PASS | openapi ≥61 paths: PASS.