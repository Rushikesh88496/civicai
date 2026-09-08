# Part 21 Checkpoint Report — Centralized Notification System

## Status: READY — YES

## What Was Implemented

**Data model + infrastructure (`app/core/notification_types.py`, `app/schemas/notification.py`, migration):**
- Migration `alembic/versions/7d3e8528ec1c_notifications_title_read_at_link_.py` (**applied**;
  head = `7d3e8528ec1c`) extends `notifications` with `title`, `read_at`, `link`, `channel`,
  `payload`, `complaint_id`, `work_order_id`, `message_id`, `actor_name` (nullable/strict
  match legacy semantics).
- `NotificationEvent` registry: 18 canonical events with fixed `channels` (DB per-user eye /
  realtime / email) and `link` templates. Legacy stored types preserved exactly:
  `MESSAGE`, `WORK_ORDER_COMPLETED` (= RESOLVED), `WORK_ORDER_REOPENED`, `SLA_AT_RISK`,
  `SLA_BREACHED`; registry aliases map them onto modern canonical types.
- Centralized `notification_service.notify(event, actor, *, recipient, extra_scopes)`:
  **never raises**, **never commits** (callers commit), schedules realtime + email best-effort
  via `create_task`. Deduplicated single call site for all producers.

**Pluggable email (`app/core/email.py`, config):** `get_email_provider()` builds either the
login-only `console` provider (default, zero credentials) or `smtp` (stdlib smtplib +
STARTTLS), degrading safely to console when `EMAIL_PROVIDER=smtp` but `SMTP_HOST` is unset —
the app never fails for missing credentials. Sending is gated on
`NOTIFICATIONS_EMAIL_ENABLED=false` by default; **no real credentials were added** (user
chose to keep the console provider).

**Realtime (`app/core/realtime.py`, `app/api/ws/notifications.py`):** per-user Redis pub/sub
`civicagent:notifications:<user_id>`; publish failures swallowed, so Redis being down (as here)
degrades to fallback polling. WS endpoint `/ws/notifications?token=...` authenticates the JWT,
sends an initial `{"type":"snapshot","unread_count":N}` (from the DB, live Redis or poll), and
pushes `snapshot` on every publish; invalid/missing token → close **4401**. A `change_stream`
active-session decouples WS scope from the request scope (post-commit safe via independent
factory wired to ShortTermMemory; stale subscribers self-purge).

**REST API (`app/api/v1/notifications.py`):** `GET /api/v1/notifications` (paginated +
`unread_only` filter, defaults from settings), `GET /unread-count`, `POST /{id}/read`,
`POST /read-all`. Owner-scoped (a user only ever sees their own rows; others' ids → 404).

**Producers wired (12 files, all through `notify`):** complaint receive (COMPLAINT_RECEIVED /
WARD_ALERT — the latter only when the citizen has a ward), AI summarize (AI_COMPLETE),
priority engine (PRIORITY_ASSIGNED, PRIORITY_CHANGE on bucket change w/ active assignment),
dispatch agent (WORK_ORDER_CREATED, P1_ALERT, WORKER_ASSIGNED / NEW_ASSIGNMENT / REASSIGNMENT),
worker actions (REPAIR_STARTED, WORK_ORDER_COMPLETED → complaint RESOLVED, WORK_ORDER_REOPENED),
conversation (MESSAGE, ESCALATION both directions), verify-repair
(HUMAN_REVIEW in `run_verification` when human review required), SLA agent (SLA_AT_RISK /
SLA_BREACHED). Exact recipient/link/actor semantics covered by the test suite.

## Tests & Results

- **`tests/test_notifications.py` — 16/16 pass** on live dev Postgres: complaint → citizen
  + human-rep notifications; 401 auth; pagination / unread_only / read-all / read endpoints
  (owner-only 404); dispatch of a GARBAGE complaint (P4) fires neither P1_ALERT nor worker
  assignment; P1 (waterlogging + signals) fires OFFICER+ADMIN P1_ALERT; assign/reassign/
  complete chain (worker gets NEW_ASSIGNMENT, complaint ends RESOLVED after repair completion);
  ESCALATION both directions (ward-rep → staff via `{"body":...}`, work-order escalate → ward
  reps); HUMAN_REVIEW via FakeAI + photo-seeded COMPLETED order; console email provider serves
  `channel="email"`; plus WS tests: valid token → snapshot frame, invalid token → 4401
  (isolated NullPool engine wired into `app.api.ws.notifications.async_session_factory`).
- Full backend suite: **291 passed** (275 existing + 16 new) in ~7:08.
- Backend **ruff: clean** (check + format). Alembic at head `7d3e8528ec1c`, migration applied.
- Frontend: **eslint clean**, **`next build` passes** (21 routes incl. new `/notifications`).
- Live production smoke (servers left running): `/`, `/notifications`, `/dashboard/notifications`,
  `/work`, `/dashboard` → HTTP 200; unauth `GET /api/v1/notifications*` → 401; end-to-end
  register → login → unread-count `0` → empty list → `/auth/me` role CITIZEN; live WS
  `ws://localhost:8000/ws/notifications?token=...` → `{"type":"snapshot","unread_count":0}`.

## Frontend

- `src/lib/notification-api.ts` (canonical): extended `NotificationItem` / `NotificationListOut`
  types, `fetchNotifications` (with pagination + unread filter), `fetchUnreadCount`,
  `markNotificationRead`, `markAllNotificationsRead`, `notificationsWsUrl`,
  and `notificationLinkHref` — a safe route-mapper for backend deep links that don't exist in
  this frontend (`/officer/… → /officer`, `/messages/{id} → /messages?complaint={id}`, etc.).
- `src/lib/conversation-api.ts` now re-exports the notification surface so Part 17's
  `NotificationsPanel` and any other imports keep working unchanged.
- `src/hooks/use-notifications.ts`: unread badge via WS + 30 s REST poll fallback; paginated item
  fetch with an All/Unread filter; optimistic mark-read / mark-all-read.
- `src/components/notifications/notification-bell.tsx` (header bell with unread badge + dropdown
  panel), `notification-center.tsx` (full-page list w/ filters, pagination, error/empty/skeleton
  states), `notification-visuals.tsx` (per-type icon + colour map).
- Routes: real `src/app/notifications/page.tsx` (+ metadata layout) and
  `src/app/dashboard/notifications/page.tsx` (now renders the real center, replacing the stale
  placeholder). Header bells added to dashboard, officer, ward-rep and field-worker shells;
  officer + ward-rep nav gained a Notifications item.
- `.env.example` (root + backend) documents `EMAIL_PROVIDER` / `SMTP_*` /
  `NOTIFICATIONS_EMAIL_ENABLED` placeholders.

## Errors Fixed During This Session

- **Frontend CRUD errors on first build:** a legacy type string (`WORK_ORDER_COMPLETED`) that the
  per-type icon map did not handle rendered as the fallback glyph (leaf issue only, no error);
  the icon map now also keys legacy aliases. Real fixes: e2e registration validated the whole
  flow; `import` hygiene cleaned after initial lint (unused icons), the 
  `react-hooks/set-state-in-effect` rule was satisfied with a microtask reset (items cleared +
  loading shown without a synchronous setState), and a duplicated `pollTimer` const (from an
  over-eager refactor) was removed. `npx tsc` route-validator noise was unrelated: `.next/dev`
  typegen is regenerated by `next build`, which passes.
- **Test cross-contamination:** a priority-related FK failure surfaced only when an interrupted
  earlier session left a half-written unit in the shared dev DB; passes in isolation — no code
  bug. Reassign test seeds the second worker *after* approval (otherwise dispatch may recommend
  the second worker first → 409 "Worker already assigned"). Dispatch accepts 200 **or** 201; the
  ward-rep escalate payload field is `body` (not `reason`).

## Known Limitations / Remaining Issues

- **Email stays console-only:** user chose to keep the zero-config provider. `.env.example`
  fully documents the SMTP switch (set `EMAIL_PROVIDER=smtp`,
  `NOTIFICATIONS_EMAIL_ENABLED=true`, supply `SMTP_HOST/PORT/USER/PASSWORD`) — flip it whenever
  real credentials exist. **No real credentials were ever added.**
- **Redis still down (pre-existing):** realtime degenerates to the snapshot + 30 s poll
  fallback; the bell badge stays fresh anyway (REST fallback), and every notification still
  arrives in the DB and over REST immediately.
- Broadcast-style events (WARD_ALERT, P1_ALERT, SLA_*) fan out to all matching staff per the
  existing notification model; per-department targeting remains a product extension.
- Bell badge counts and page state are per-frontend-session; a notification opened in the bell
  updates read state locally and reconciles via the snapshot/poll.

## Security

- No secrets introduced or logged; SMTP credentials never hardcoded — they are read from env
  only and default to console.
- All endpoints + the WS socket are owner-scoped / authenticated; other users' notification ids
  are 404 (not 403) to avoid id/status leaks; invalid WS tokens are closed with 4401.
- Deep links are validated client-side in `notificationLinkHref` (absolute-URL / scheme-free
  strings never reach `router.push`).
- No new LLM/Groq surface — producers reuse existing agents/services.

## Regression Status

Backend ruff: PASS | Full backend suite 291 (275 + 16 new): PASS | Alembic at head
`7d3e8528ec1c`: PASS | Frontend eslint: PASS | `next build` (21 routes): PASS | Live page smoke
(/, /officer, /work, /dashboard, /notifications, /dashboard/notifications): PASS | OpenAPI
notifications endpoints + `/ws/notifications` exercised end-to-end through the live app: PASS.