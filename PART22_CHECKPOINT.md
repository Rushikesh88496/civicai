# Part 22 Checkpoint Report — Civic Analytics + Citizen Satisfaction

## Status: READY — YES

## What Was Implemented

**Citizen satisfaction ratings (`app/models/complaint_rating.py`, migration):**
- Migration `alembic/versions/8f4e9d2c1b0a_complaint_ratings.py` (**applied; head =
  `8f4e9d2c1b0a`, chained from `7d3e8528ec1c`) creates `complaint_ratings` with a
  **unique** `complaint_id` (FK CASCADE), `user_id` (FK RESTRICT), `rating` Int, nullable
  `comment` Text, timestamps.
- `ComplaintRating` model exported from `app/models/__init__.py`; relationship `complaint`.
- New endpoint file `app/api/v1/ratings.py` (registered in `app/api/router.py` after
  complaints): `POST /api/v1/complaints/{complaint_id}/rating` → 201 `RatingOut`.
  CITIZEN-only role gate; owner check; 404 `ComplaintNotFound`, 403 `RatingAccess`,
  409 `AlreadyRated`, 409 `ComplaintNotResolved`. Rating allowed only for complaints whose
  current status is in the resolved family **or** that have a resolved-family row in
  `complaint_status_history`.
- `app/schemas/rating.py` (`RatingIn` ge=1 le=5, comment max 500; `RatingOut`) and
  `app/services/rating_service.py` with typed errors.

**Civic analytics API (`app/api/v1/analytics.py`, `app/services/analytics_service.py`,**
`app/schemas/analytics.py`)** — staff role gate (OFFICER / ADMIN / WARD_REPRESENTATIVE);
WARD_REPRESENTATIVE is auto-scoped to their own ward via the shared
`_branch_complaint_scope`:
- `GET /api/v1/analytics/overview` — `AnalyticsOverview` with filtered KPIs + six chart
  series. Filters: `date_from` / `date_to` (on `created_at`; ISO timestamps, invalid → 422),
  `ward_id`, `category`, `priority` (latest `DynamicPriority` bucket), `department`
  (latest `ComplaintDepartmentHistory`).
- KPIs: total / resolved / resolution rate; response time (earliest status-history row not
  in SUBMITTED/OPEN — operational response, not first message) and resolution time
  (earliest resolved-family row, `updated_at` fallback) avg + median + counts; SLA
  compliance (within ≤ due_at / overdue incl. open past deadline; orders w/o deadline
  excluded); AI triage reach; escalations; citizen satisfaction avg + 1–5 distribution.
- Charts: `complaints_over_time` + `resolution_trend` (daily ≤ 92-day span, else monthly),
  categories, wards, departments (completion + SLA), `sla_performance` (within vs overdue
  per priority).
- `GET /api/v1/analytics/heatmap` → `HeatmapOut` clusters (grid 0.005° ≈ 550 m; weights
  P1/P2/P3/P4 = 1.0 / 0.75 / 0.5 / 0.25, capped at 500 clusters).
- `GET /api/v1/analytics/export` → CSV (`text/csv`, `Content-Disposition` attachment) of
  the filtered complaint set.
- SQLAlchemy-safe aggregations (plain `Select` in `in_()`, no subquery coercion warnings).

## Tests & Results

- **`tests/test_analytics.py` — 11/11 pass** on live dev Postgres: RBAC (citizen +
  field-worker 403, ward-rep OK); overview totals/filters (date range, priority latest-
  bucket, department latest-history); event-mapped complications (AI-triage fee,
  escalation); response/resolution timing via status history; SLA within/overdue/compliance
  (open-overdue counted); timeseries daily vs monthly bucketing; CSV export shape +
  filename; heatmap clustering + weights; ward-rep own-ward scoping; satisfaction
  distribution.
- Full backend suite: **302 passed** (291 existing + 11 new) in ~8:45.
- Backend **ruff: clean** (`check app tests alembic`). Alembic at head `8f4e9d2c1b0a`,
  migration applied.
- Frontend: **`tsc --noEmit` clean**, **eslint clean**, **`next build` passes** (23 routes
  incl. `/officer/analytics` and `/ward-rep/analytics`).
- Live production smoke (servers restarted, left running): `/officer`,
  `/officer/analytics`, `/ward-rep`, `/ward-rep/analytics`, `/dashboard`, `/login` → HTTP
  200; officer `GET /analytics/overview|heatmap|export` → 200 (overview totals, CSV
  bytes, `Content-Disposition` filename); **citizen → 403**; ward-rep endpoint responds
  under the same staff gate.

## Frontend

- `src/lib/analytics-api.ts` (canonical): types mirroring the backend schemas
  (`AnalyticsOverview`/`AnalyticsKpis`/`AnalyticsCharts`/`HeatmapOut`/…),
  `fetchAnalyticsOverview`, `fetchAnalyticsHeatmap`, `downloadAnalyticsCsv` (auth fetch →
  blob → `Content-Disposition` filename), filter option lists (categories from shared
  `CATEGORY_LABELS`, departments, P1–P4 priorities).
- `src/components/analytics/civic-analytics.tsx`: filter bar (date from/to, ward
  dropdown from `fetchGeoWards`, department, category, priority + clear), CSV export +
  refresh buttons, **9 KPI cards**, recharts series (complaints over time, resolution
  trend, category and top-12 ward bars, department performance table, stacked SLA
  within/overdue, satisfaction pie), loading / error-with-retry / empty states.
- `src/components/analytics/civic-analytics-heatmap.tsx`: Leaflet canvas mirroring the
  command-center pattern — `L.circleMarker` sized/coloured by normalized weight with
  count popups and auto-fit bounds.
- Pages `src/app/officer/analytics/page.tsx` + `src/app/ward-rep/analytics/page.tsx`;
  “Analytics” nav items added to both officer and ward-rep layouts (active-state logic
  preserved). Recharts 3.10.1 added (React-19-compatible).

## Errors Fixed During This Session

- **Test cross-contamination (regression):** the analytics cleanup fixture deleted **all**
  `%@example.com` users, which removed the shared demo seeds
  (`citizen@example.com`, `admin@example.com`, …) → `test_auth.test_rbac_role_gate`
  failed on the full-suite run. Fixed by narrowing the filter to the generated test-user
  pattern `%-@example.com`; re-ran the affected files then the whole suite
  (**302 pass**) after restoring the seeds with the idempotent `seed.py`.
- **recharts v3 TS types:** `Tooltip` label/value props are `ReactNode` (no longer
  `string`) and Pie label props differ — formatter/label handlers now `String()`-coerce,
  and the pie label reads `entry.payload?.rating/.count`.
- No API/behavioural bugs surfaced; analytics tests caught and pinned the intended
  semantics (response time via status history, open-overdue SLA, monthly bucketing).
- Pollution from an earlier full-suite run left ~19 test-created complaints
  (`vf-*`/`fw-*` users, `ward_id=NULL`) in the shared dev DB — they are residual data
  from pre-existing test modules (not cleaned by their own teardowns), verified absent
  of any Part 22 logic issue (ward-rep scoping is specifically covered by the tests).

## Known Limitations / Remaining Issues

- **SLA / ratings show 0 in the live demo DB right now** because no work orders or
  resolved-and-rated complaints currently exist there (orders/ratings were cleaned by
  earlier test runs); the analytics endpoints return the correct shapes/zeros and the
  seeded demo complaints power the other charts. Re-run `backend/seed.py` or submit
  real complaints to populate.
- Email stays console-only (pre-existing); Redis still down (pre-existing) — no impact on
  analytics.
- Ward filter dropdown lists all wards from `/geo/wards` (officer view); ward-rep data is
  scope-limited server-side regardless.

## Security

- No new secrets/config added; nothing logged beyond standard API access.
- Analytics + rating endpoints are role-gated server-side (staff gate / CITIZEN-only);
  ward representatives can only ever see their own ward’s aggregates; ratings are
  owner-scoped and blocked until a complaint is genuinely resolved, with 404/409/403
  semantics that don’t leak other users’ ids.
- CSV export uses the same auth as the REST API; dates are validated server-side
  (invalid ISO → 422).
- No new LLM/Groq surface — analytics is deterministic SQL aggregations only.

## Regression Status

Backend ruff: PASS | Full backend suite 302 (291 + 11 new): PASS | Alembic at head
`8f4e9d2c1b0a`: PASS | Frontend `tsc`: PASS | Frontend eslint: PASS | `next build`
(23 routes): PASS | Live page smoke (`/officer`, `/officer/analytics`, `/ward-rep`,
`/ward-rep/analytics`): PASS | Live API smoke (overview / heatmap / export 200, citizen
403): PASS.