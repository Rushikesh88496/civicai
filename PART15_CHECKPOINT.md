# Part 15 Checkpoint Report — Municipal Officer Command Center

## Status: READY — YES

## What Was Implemented

**Backend service (`app/services/command_center_service.py`)** — Part-15 facade with five
read endpoints (role-scoped for OFFICER / ADMIN / WARD_REPRESENTATIVE):

- **KPIs** — total complaints, P1..P4 counts (read from the **latest** priority-history bucket
  per complaint), pending / in-progress / resolved status buckets, and SLA breaches (open work
  orders whose due date has passed).
- **Priority queue** — paginated, with filters on status / category / priority / department /
  ward / date range and free-text search over title & description. Collapses to the latest
  priority, department and ward per complaint.
- **Map** — complaints (with location) as dots, work orders as squares, wards, and per-ward
  weighted **hotspots** (priority-weighted open-complaint load).
- **AI activity** — per-agent run aggregation (total / pending / running / completed / failed)
  over `agent_runs` (`triage`, `vision`, `correlation`, `dispatch`, `priority`, `context`,
  `routing`), each with `enabled` + `last_activity_at`. **GIS is synthesized** (`enabled=False`,
  0 runs) because no GIS *agent* exists — geography is a service, not an agent.
- **Snapshot** — the single realtime payload (`kpis` + `ai_activity` + `changed_at`).

The "latest priority" queries were the subtle part: `_max_priority_calc` /
`_latest_priority_priority` / `_latest_priority_score` / `_latest_department_subq` are now
**correlated** to `Complaint` (verified: an older P3 + newer P2 returns P2 in both queue and
KPIs).

**Realtime — WebSocket (`app/api/ws/command_center.py`, `/ws/command-center`)**:
- Token-authenticated via `?token=<access token>` (browsers can't set an `Authorization`
  header on a WS). Gated to OFFICER / ADMIN / WARD_REPRESENTATIVE; invalid/non-staff tokens are
  rejected before accept.
- Pushes an initial **snapshot** on connect, then refreshes on Redis `COMMAND_CENTER_CHANNEL`
  pub/sub (published from `agent_run_service.finalize_run` after every agent run commit).
- **Degrades gracefully when Redis is down** (by design) to a slow periodic snapshot refresh —
  no busy-loop; answers client `ping` / `refresh` messages.
- `app/core/realtime.py` `publish_command_center_refresh()` is best-effort (never raises when
  Redis is unavailable).

**API (`app/api/v1/command_center.py`)** — registered in `app/api/router.py`:
`GET /api/v1/command-center/{kpis|queue|map|ai-activity|snapshot}` (staff-gated,
WARD_REPRESENTATIVE scoped to own ward). **5 new paths** (48 → **53** in openapi).

**Frontend — `/officer` route group (staff-gated)**:
- `frontend/src/lib/officer-api.ts` — typed client mirroring `citizen-api.ts`
  (`authorizedGet` + `getAccessToken`), the 5 commands, plus a `commandCenterWsUrl()` helper.
- `frontend/src/components/dashboard/command-center.tsx` — **9 KPI cards** (Total, P1..P4,
  Pending, In Progress, Resolved, SLA Breaches), a **priority queue** with status/priority/
  department filters + free-text search + pagination (loading/empty/error states), a Leaflet
  **incident map** with a **hotspot-wards** side panel, and an **AI Agent Activity** panel
  (Triage / Vision / Duplicate / Context / Priority / Routing / Dispatch + GIS-off) showing
  pending/running/completed/failed bars.
- `command-center-map.tsx` (dynamic, SSR-off) + `command-center-map-canvas.tsx` (Leaflet:
  colored dots by priority, blue squares for work orders, bound to data).
- `frontend/src/components/officer/officer-layout.tsx` + `src/app/officer/layout.tsx` +
  `src/app/officer/page.tsx` — `ProtectedRoute` gated to
  `["OFFICER","ADMIN","WARD_REPRESENTATIVE"]`; a 30s realtime poll fallback + manual Refresh.

## Tests & Results

- Backend **`tests/test_command_center.py` — 10/10 pass**:
  - `test_requires_auth` (401), `test_citizen_forbidden` (403).
  - `test_kpis_aggregate` / `test_kpis_sla_breach` (latest-priority + SLA-due deltas).
  - `test_queue_pagination_and_search` (search-token isolation, page/total_pages).
  - `test_map_returns_complaints_wards_hotspots`.
  - `test_ai_activity_aggregates_runs` (incl. synthesized `gis` = 0 runs, enabled False).
  - `test_ward_rep_scoped_to_own_ward` (only own ward's complaints in queue/KPIs/map).
  - **NEW `test_websocket_officer_receives_snapshot`** — officer connects to
    `/ws/command-center`, receives an initial `snapshot` with `kpis`, and a refreshed snapshot
    after a client `refresh`. **This catches the websocket route-wiring regression below.**
  - **NEW `test_websocket_citizen_rejected`** — a citizen token is rejected (no snapshot).
- Ruff: **clean** on the whole backend (`ruff check .` run on changed files + full app).
- Regression (storage/LLM-independent): health+auth+citizen+complaints+priority+context+
  correlation+ai_service+dispatch+routing = **155 passed**; the only **3** failures are the
  pre-existing S3/MinIO media-upload outage (`Upload storage is unavailable.` → 500), unrelated
  to Part 15.
- Frontend: **`npx eslint` clean** (0 errors), **`npx tsc --noEmit` clean**, **`npx next build`
  passes**; `/officer` route listed in the build output.

## Live E2E (HTTP + WebSocket against the running stack)

- Restarted uvicorn; `/api/v1/health` 200; `/openapi.json` serves **53** paths incl. the **5**
  Part-15 REST routes (`/api/v1/command-center/*`).
- Seeded **officer** login (`officer@example.com`):
  - `GET /kpis` → total=64, p1=0, p2=0, p3=0, p4=1, pending=59, in_progress=2, resolved=2,
    sla_breaches=0.
  - `GET /queue` → total=64, page=1, total_pages=13, 5 items.
  - `GET /map` → complaints=64, work_orders=2, wards=18, hotspots=18.
  - `GET /ai-activity` → **8 agents** (triage/vision/correlation/context/priority/routing/
    dispatch enabled; **gis enabled=False, total=0**).
  - `GET /snapshot` → `type=snapshot` + `changed_at`.
- **RBAC**: citizen login → `GET /kpis` → **403**.
- **WebSocket**: officer connects to `ws://localhost:8000/ws/command-center?token=…`
  (Origin `http://localhost:3000`) → initial `snapshot` (kpis total=64) → `refresh` →
  second `snapshot`.

## Errors Fixed During This Session

- **WebSocket 403 at handshake (root-cause bug):** the `main.py` WS route wrapper
  `async def command_center_ws(websocket, token: str = Query(""))` had an **unannotated**
  `websocket` parameter, so FastAPI treated it as a *query* field (`loc: ['query','websocket'],
  Field required`) and rejected every connection with 403 before `accept()`. Fixed by annotating
  `websocket: WebSocket`. Confirmed the route now sends a real snapshot (in-process + live over
  the network). **A dedicated WebSocket test was added to lock this in.**
- `react-hooks/set-state-in-effect`: the command-center data effect originally called an async
  wrapper that called `setState` synchronously. Rewritten to fetch in `.then`/`.catch` callbacks
  (the pattern already used by `use-dashboard-data.ts`), driving re-fetch via a `tick` state.
- `CommandCenter`'s WS/polling and map canvas cleaned of unused vars / dead hotspot loop
  (hotspots have no centroid, so they surface in the side panel instead of markers).

## Known Limitations / Remaining Issues

- Active WS realtime requires Redis; when Redis is down (as in this environment) the panel
  falls back to a 30s poll — graceful, by design.
- Map hotspots are presented as a ranked ward panel (the `/map` payload aggregates per-ward
  weight/count but wards have no centroid in this dataset, so no choropleth markers).
- S3/MinIO outage (pre-existing) blocks the media-upload tests; unrelated to Part 15.

## Security

- No secrets introduced or logged. Command-center reads are staff-gated
  (OFFICER/ADMIN/WARD_REPRESENTATIVE); citizens get **403**; unauthenticated **401**;
  WARD_REPRESENTATIVE is scoped to their own ward only. The WebSocket validates the access
  token from the query param and rejects non-staff before accepting.

## Regression Status

- Backend ruff: PASS | `test_command_center.py` (10): PASS | health+auth+citizen+complaints+
  priority+context+correlation+ai+dispatch+routing (155): PASS (3 pre-existing S3 media
  failures) | Frontend eslint: PASS | `tsc --noEmit`: PASS | `next build`: PASS | Live REST E2E
  (KPIs/queue/map/AI/snapshot + citizen 403): PASS | Live WS E2E (snapshot + refresh): PASS |
  openapi 53 paths: PASS.
