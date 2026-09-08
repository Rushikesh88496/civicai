# Part 12 Checkpoint Report — Dynamic Priority & Risk Engine

## Status: READY FOR NEXT PROMPT — YES

## What Was Implemented

**Deterministic engine (`app/services/priority_engine.py`)** — a pure, dependency-free,
no-LLM scorer that maps the seven priority inputs onto a single 0–100 `score` and a
`DynamicPriority` bucket, with every factor fully explainable:

- **Severity** — from the complaint's stored `priority` (set upstream by the triage
  agent as an *input only*; the engine never lets an LLM set the numeric score):
  LOW→0.10, MEDIUM→0.35, HIGH→0.65, CRITICAL→0.90.
- **Population impact** — count of `User` rows whose `ward_id` equals the complaint's
  ward (population proxy; the ward model has no population column).
- **Critical infrastructure proximity** — hospitals (weighted 2×) / schools / bus
  stops read from the context agent's `InfrastructureContext`.
- **Weather** — condition + rainfall read from the context agent's `WeatherContext`,
  mapped via `_RAINY_CONDITIONS` and a `PRIORITY_WEATHER_RAIN_MM` rainfall band.
- **Complaint count** — historical prior complaints near the location.
- **Historical recurrence** — same-ward prior complaints over the window.
- **Time unresolved** — age in hours against a `PRIORITY_TIME_BAND_HOURS` band.

Each input normalizes to a 0–1 unit; `score_from_units` re-normalizes the weighted sum
**over present inputs** (`raw/total_w`) so missing inputs contribute 0 and never distort
the others, then clamps to 0–100. Buckets: `[80,100]→P1_CRITICAL`, `[60,80)→P2_HIGH`,
`[40,60)→P3_MEDIUM`, `[0,40)→P4_LOW`. `score_priority` assembles the explainable
`factors` breakdown (ordered by contribution, descending) plus `inputs`, `summary`,
`previous_*` and `changed`. Configurable weights (default sum 1.0): severity 0.30,
weather 0.10, location 0.15, crowd 0.20, history 0.10, time 0.15 (crowd =
`0.5*population + 0.5*complaint_count`).

**Agent (`app/agents/priority_agent.py`)** — LangGraph `START → compute → persist → END`,
`AGENT_NAME="priority"`, no LLM. `_load_context` reads the latest `agent="context"` run
and validates it into `ContextOutput`; missing/malformed context degrades to neutral (0),
never fails. Population/infrastructure/historical signals come from the context agent and
the live DB. `run(...)` mirrors the context agent (create_run, commit, invoke, duration,
reload). Each computation persists a `PriorityOutput` to `agent_runs` (`agent="priority"`)
**and** appends a `ComplaintPriorityHistory` row (score, priority, previous_score,
changed, inputs JSONB, factors JSONB, summary, calculated_at).

**Change detection** — `changed = prev_score is None or abs(score - prev_score) >=
PRIORITY_CHANGE_THRESHOLD (15.0)`; previous values from the newest
`complaint_priority_history` row.

**Model + Migration** — `DynamicPriority` enum added to `enums.py`;
`ComplaintPriorityHistory` model (`complaint_priority_history` table) with a
`priority_history` relationship on `Complaint`; migration `b3c4d5e6f7a8`
(applied; `alembic heads = b3c4d5e6f7a8`).

**Schemas (`app/schemas/priority.py`)** — `PrioritySignalInputs`, `PriorityFactor`,
`PriorityOutput`, `PriorityRunOut`, `PriorityRunResponse`, `PriorityRunIn`,
`PriorityHistoryEntry`, `PriorityHistoryOut`.

**Service (`app/api/priority_service.py`)** — `PriorityNotFoundError` /
`PriorityAccessError`, `run_priority`, `get_priority_result`, `get_priority_history`,
all access-enforced via `_load_complaint` + `user_can_view`.

**API (`app/api/v1/complaints.py`)** — `POST /{id}/priority` (PriorityRunResponse),
`GET /{id}/priority-result` (PriorityRunOut | None), `GET /{id}/priority-history`
(PriorityHistoryOut), with a `_priority_error` mapper (404/403/400).

**Config (`app/core/config.py` + `backend/.env.example`)** —
`PRIORITY_WEIGHT_SEVERITY/WEATHER/LOCATION/CROWD/HISTORY/TIME`,
`PRIORITY_THRESHOLD_P1=80/P2=60/P3=40`, `PRIORITY_CHANGE_THRESHOLD=15.0`,
`PRIORITY_WEATHER_RAIN_MM=5.0`, `PRIORITY_POPULATION_BAND=1000.0`,
`PRIORITY_COMPLAINT_BAND=10.0`, `PRIORITY_HISTORY_BAND=15.0`,
`PRIORITY_TIME_BAND_HOURS=168.0`.

**Frontend**
- `frontend/src/lib/citizen-api.ts`: `DynamicPriority` + `PrioritySignalInputs`,
  `PriorityFactor`, `PriorityResult`, `AiPriorityRun`, `RunPriorityResponse`,
  `PriorityHistoryEntry`, `PriorityHistoryOut` types and `fetchPriorityResult` /
  `runPriorityEngine` / `fetchPriorityHistory`.
- New `priority-index-card.tsx` — **Priority Index** card with
  loading/empty/error/success states and a "Score priority"/"Re-score" affordance;
  shows a circular score gauge (score/100), the P1–P4 bucket badge (color-coded),
  a score bar with P4…P1 guide, an explainable "Why this score" factor breakdown
  (factor, points, description, contribution bar), a previous-bucket line, and an
  append-only **score history** list (bucket, timestamp, was-score, score). Wired
  into `complaint-detail-view.tsx` right after `ContextIntelligenceCard`.

## Migration
`b3c4d5e6f7a8` ("complaint_priority_history + dynamic_priority enum") — created and
**applied** to the live dev DB. Verified: table columns, enum
`['P1_CRITICAL','P2_HIGH','P3_MEDIUM','P4_LOW']`, and both indexes
(`ix_complaint_priority_history_complaint_id`, `ix_complaint_priority_history_priority`).
`alembic heads` = `b3c4d5e6f7a8`.

## Tests & Results
- Backend: **`tests/test_priority.py` — 39/39 pass**:
  - **Boundary scores (deterministic)** — `score_from_units` with a single active
    weight reproduces exactly 0 / 1 / 49 / 50 / 69 / 70 / 89 / 90 / 100, and each is
    bucketed correctly by `priority_from_score`; a cross-check confirms the engine's
    boundaries land in the same buckets the mapping claims.
  - **Missing inputs** — empty units → score 0 / P4; present signals are never
    distorted by absent ones.
  - **Extreme values** — saturation pushes the score ≥ 90 (P1_CRITICAL) while staying
    clamped 0–100; all-neutral stays ≤ 10 (P4); factor sums stay non-negative and
    bounded; factor ordering is deterministic.
  - **Agent integration (live DB)** — `PriorityAgent.run` persists a `PriorityOutput`
    (`agent="priority"`, `SUCCEEDED`), appends a history row with
    `previous_score=None`/`changed=True`; a re-run sets `previous_score` and computes
    `changed` from `PRIORITY_CHANGE_THRESHOLD`.
  - **API + RBAC** — 401 unauthenticated, 403 cross-owner, 404 unknown complaint; a
    full run + `priority-result` GET + `priority-history` GET; `result` is `None`
    before any run; service-layer history access is enforced.
  - **Config** — weights/thresholds/change-threshold exposed and sanity-checked.
- Ruff: **clean on the entire backend** (`ruff check .`).
- Regression (storage-independent): `test_health.py`+`test_geo.py` (26),
  `test_correlation_agent.py` (13), `test_citizen.py`+`test_auth.py` (22),
  `test_context.py` (14) — all passed. `test_complaints.py` media-upload failures are
  the **pre-existing** S3/MinIO outage, unrelated to Part 12.
- Frontend: **`npm run lint` clean**, **`npx tsc --noEmit` clean**,
  **`npm run build` passes** (Next 16 / TypeScript). New icons (`Gauge`,
  `TrendingUp`) confirmed present in lucide-react 1.39.0.

## Live E2E (via HTTP against the running dev stack)
- Restarted the backend (old process predated the new routes). `/api/v1/health` 200;
  `/openapi.json` serves all three priority routes.
- Registered a citizen, created a complaint at 17.4327, 78.3885.
- `POST /complaints/{id}/priority` → `SUCCEEDED`, **score 11 / P4_LOW** (severity input
  defaulted to LOW for a fresh complaint), `changed=True` on first run, summary
  "Priority P4_LOW score 11/100 - biggest driver: Severity", 6 explainable factors
  (top = Severity, 10.5 pts).
- `GET /{id}/priority-result` → persisted run `agent=priority`, `SUCCEEDED`.
- `GET /{id}/priority-history` → 1 entry.
- **Re-run** on the same complaint → `SUCCEEDED`, `score=11`, `previous_score=11`,
  `changed=False` (no movement) — history grew to **2** entries and the latest entry
  records `previous_score=11` (append-only persistence + change detection verified).
- Negative path: unauthenticated POST → **401**.
- Frontend detail pages serve **200**; ESLint / TS / production build all compile the
  new Priority Index card.

## Errors Fixed During This Session
- Initial `tests/test_priority.py` had an incorrect assertion interpreting the
  `present` flag as tied to a zero contribution (severity is always scored). Replaced
  with deterministic, semantically-correct assertions.
- Trailing-newline / import-sort ruff nits in the new test file and the migration were
  auto-fixed; full backend lint is clean.

## Known Limitations / Remaining Issues
- **Severity is supplied by the triage agent** (LOW/MEDIUM/HIGH/CRITICAL) as an input;
  the engine only maps it deterministically. Until triage has run, a fresh complaint
  defaults to severity LOW (hence a low score), which is intentional.
- Population impact is a **ward-resident-count proxy**; accurate census population per
  ward is not modeled.
- Weather/infrastructure/historical inputs depend on the context agent having run;
  without it they degrade to neutral (0) rather than failing.
- Full-suite `pytest` still hangs under this host's memory pressure; suites are run
  per-file. Pre-existing S3/MinIO outage still blocks media-upload tests — both
  unrelated to Part 12.

## Security
- No secrets introduced or logged. The engine is fully deterministic — no LLM call,
  no external service, no credential. The three `/priority*` endpoints require an
  authenticated user and enforce complaint ownership/RBAC (403 cross-owner,
  401 unauthenticated, 404 unknown). All weight/threshold tuning is via environment
  variables; no key is hardcoded.

## Regression Status
- Backend ruff: PASS | `test_priority.py` (39): PASS | health+geo (26) + correlation
  (13) + citizen/auth (22) + context (14): PASS | Alembic head `b3c4d5e6f7a8`: PASS |
  Frontend lint: PASS | `tsc --noEmit`: PASS | Frontend build: PASS | Live E2E
  (register → create → run priority → result → history → re-run change detection →
  401): PASS | Negative paths (401/403/404): PASS | Manual UI: Priority Index card
  linted, type-checked, built, wired into detail view; detail pages render 200.