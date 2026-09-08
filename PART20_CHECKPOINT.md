# Part 20 Checkpoint Report — SLA Monitoring Agent

## Status: READY — YES

## What Was Implemented

**Configurable SLA rulebook (`sla_policies`) — replaces the hard-coded mapping:**
- New `SlaPolicy` model (table **`sla_policies`**) — a rule is a specificity match
  over (`priority`, `department`, `category`) with wildcards (`NULL`) allowed, plus
  `sla_hours`, `at_risk_percent` (default 0.75 = final quarter warning), `escalate_on_breach`,
  `active`, and audit columns.
- Migration `alembic/versions/e2e3f4a5b6c7_sla_policies.py` (**applied**; head =
  `e2e3f4a5b6c7`) seeds the four built-in defaults P1=24 / P2=48 / P3=72 / P4=168 so
  existing dispatch behavior is preserved out of the box; officers add more-specific
  department / category rules on top at runtime.
- `sla_policy_service.resolve` — among ACTIVE rules matching the order's three
  dimensions, the rule with the most concrete (non-null) dimensions wins, so a
  `P1 + ROADS` rule beats the plain `P1` default. NULL-safe duplicate detection
  (two all-wildcard or two identical rules are duplicates), validation
  (`sla_hours > 0`, `0 < at_risk_percent <= 1`, at least one constrained dimension),
  `SlaPolicyNotFoundError` / `SlaPolicyValidationError`.

**SLA computation (`services/sla_service.py`):** `compute_snapshot` produces per-order
state `ON_TRACK / AT_RISK / BREACHED / COMPLETED` + progress (0..1) + human countdown
("3h" / "overdue 2d 4h"). The SLA clock anchors at **approval time** (`approved_at`),
falls back to `due_at - sla_hours` for pre-feature orders, then `created_at`. `scan`
excludes terminal states (CLOSED / REJECTED), marks finished orders COMPLETED, and with
`backfill=True` (agent path) persists a missing `sla_hours` / `due_at` from the resolved
rule. `list_sla_orders` returns a severity-sorted (breached → at-risk → on-track) live
board with state / department / priority / search filters + pagination; `latest_run`
surfaces the newest persisted scan.

**SLA monitor agent (`agents/sla_agent.py`)** — deterministic LangGraph
`START → scan → escalate → persist → END`, `agent="sla_monitor"`, injectable `now`
for simulated-time tests, and **no LLM**:
- **escalate** compares against the previous SUCCEEDED run and raises
  `SLA_AT_RISK` / `SLA_BREACHED` notifications to all active OFFICER / ADMIN staff
  **only on a transition** into that state (breach when prior ≠ BREACHED; at-risk when
  prior is None/ON_TRACK) — repeat runs never spam, and an AT_RISK → BREACHED edge
  fires exactly one fresh breach alert.
- **persist** writes the structured `SlaScanOutput` (orders + counts +
  notifications_sent) to `agent_runs` with trace events `sla.started` / `sla.checked` /
  `sla.{state.lower()}` and reuses `create_run` / `finalize_run` / `publish_command_center_refresh`.

**Backend API — `/api/v1/sla`** (registered in the router between verifications and
field worker): `GET /orders` (live board), `POST /run` (trigger, optional
department/priority filters), `GET /run` (latest run), `GET/POST/PUT/DELETE /policies`.
Staff-only via `require_roles(OFFICER, ADMIN, WARD_REPRESENTATIVE)` + explicit
`_require_staff`; duplicates → 409, missing policy → 404, body validation → 422.

**`due_at` is now actually written (previously only read):** `work_order_service`
gains `_apply_sla_deadline` called on **approve / assign / reassign** (clock starts at
`approved_at`), and the dispatch agent's hard-coded `_sla_hours(priority)` was replaced
by `_resolve_sla_hours` → `sla_policy_service.resolve` (no test references it; behavior
preserved by the seeded defaults).

**Command center:** new `sla_at_risk` KPI (open orders whose remaining epoch ≈
`due_at − now ≤ sla_hours × 900`), `AGENT_LABELS["sla_monitor"] = "SLA Monitor"`.

**Officer frontend:**
- `lib/officer-api.ts` — `authorizedRequest` helper; SLA types; `fetchSlaOrders`,
  `runSlaMonitor`, `fetchSlaRun`, `fetchSlaPolicies`, `create/update/deleteSlaPolicy`;
  `CommandCenterKpis.sla_at_risk`.
- `components/dashboard/command-center.tsx` — "SLA At Risk" KPI card (orange when
  > 0), `sla_monitor` in the AI Agent Activity list, mounts `<SlaMonitor />`.
- New `components/officer/sla-monitor.tsx` — severity stat chips + state filter tabs,
  desktop table / mobile cards with per-order progress bars and countdown, "Run SLA
  Check" button, 30 s auto-refresh, plus a PolicyManager / PolicyForm panel to add /
  edit / delete / toggle rules (surface validation errors), reusing the repo's
  async-`.then` setState pattern.

**Worker frontend:** `WorkerJob` gains `sla_state` / `sla_progress` / `sla_remaining_seconds`
/ `sla_remaining_human` (computed in `field_worker_service._job_out` via
`sla_service.compute_snapshot` for dashboard, nearby and detail), and
`/work/orders/[id]` shows an `SlaBanner` (green on-track / amber at-risk / red breached
bar, progress fill, remaining + due time) in the workflow panel.

## Tests & Results

- **`tests/test_sla_monitor.py` — 5/5 pass** (real live-dev Postgres, simulated
  `now`): four-state + counts + **backfill** (sla_hours/due_at persisted from P1=24h);
  escalation **transition-only + no-repeat** dedup across three runs; **most-specific
  rule wins** (ROADS+P1 12h beats P1 default 24h, WASTE keeps 24h); policy API
  validation (403 citizen, duplicate 409, bad shape 422, PUT replace, DELETE 204/404);
  board + filters (state / search-by-order-id) + run trigger + RBAC (401 / 403 / 200).
- Full backend suite: **275 passed** (270 existing + 5 new) in ~7.5 min.
- Backend **ruff: clean** (check + format). Alembic at head `e2e3f4a5b6c7`,
  migration applied.
- Frontend: **eslint clean**, `npx tsc --noEmit` clean, **`next build` passes**
  (all 20 routes). Production-server smoke: `/`, `/officer`, `/work`,
  `/work/orders/test-id` all HTTP 200.

## Errors Fixed During This Session

- **`due_at` was read but never persisted** — the SLA clock had no deadline. Wired
  `_apply_sla_deadline` into approve/assign/reassign (base = approval time) and made
  the agent **backfill** missing deadlines from the rulebook.
- **Hard-coded dispatch SLA hours** (`_sla_hours(priority, settings)`) conflicted with
  the configurable rulebook — removed in favor of `_resolve_sla_hours` through
  `sla_policy_service.resolve`.
- **PUT /sla/policies returned 500 (MissingGreenlet)** after update — `updated_at` is
  expired post-commit; added `await db.refresh(rule)` before model validation.
- **Pydantic enum-serializer warnings** — snapshot `state` was assigned a `str` on a
  `SlaState`-typed field; assignments now use real enum members.
- **Strict eslint** — `react-hooks/set-state-in-effect` in the SlaMonitor board effect;
  refactored the fetch chain into `.then(...)` per the repo pattern.
- **Ruff** — E501 line-lengths in `sla.py` / `sla_agent.py` / `sla_policy_service.py`
  and an indentation typo; all clean now.
- **Test pollution** — `_notify` fans out to every active OFFICER/ADMIN user in the
  shared dev DB (hundreds accumulated across parts), so notification assertions are
  scoped to one dedicated staff user.

## Known Limitations / Remaining Issues

- **Broadcast fan-out:** SLA breach/risk alerts go to *all* active OFFICER/ADMIN users,
  not per-department — consistent with the existing notification model. Per-role or
  per-department targeting would be a product extension.
- **N+1 on the worker board:** each dashboard order does a small policy-resolution
  query; fine at current volumes, but could be eager-loaded if lists grow.
- `no_deadline` orders (no resolved rule and no persisted deadline) read "No SLA
  deadline set"; the at-risk/breach UI is driven purely from the seeded P1..P4 defaults
  until an officer adds department/category rules.
- Redis still down (pre-existing) — command-center freshness relies on the 30 s poll,
  no live push.

## Security

- No secrets introduced or logged; no LLM / Groq involved (deterministic agent) so no
  new provider surface.
- All `/sla` endpoints are staff-only via `require_roles` + `_require_staff`; citizens
  get 403, unauthenticated 401. Policies RUD are staff-managed with id-scoped responses.
- The agent persists its scan as read-only structured output and only *notifies*; it
  never mutates order status or assignments.

## Regression Status

Backend ruff: PASS | Full backend suite 275 (270 + 5 new): PASS | Alembic at head:
PASS | Frontend eslint: PASS | `tsc --noEmit` + `next build`: PASS | Production page
smoke (/, /officer, /work, /work/orders/[id]): PASS | OpenAPI /sla routes exercised
end-to-end through the live app (ASGI): PASS.