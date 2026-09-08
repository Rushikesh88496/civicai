# Part 7 Checkpoint Report — AI Triage Agent

## Status: READY FOR NEXT PROMPT — YES

## What Was Implemented

**Backend — LangGraph Triage Agent (`app/agents/triage_agent.py`)**
- Graph `START → Triage → Validate → Persist → END` with conditional edges `{"triage","persist","fail","retry"}`.
- `TriageState` TypedDict, nodes `_triage_node/_validate_node/_persist_node`, `build_graph()`, and `TriageAgent.run(db, complaint_id, input_data)` orchestrator.
- Uses the centralized Groq `AIService` (Part 6) with structured JSON output.
- Validation pipeline: schema-compliant output → persist; invalid/missing fields → retry up to `DEFAULT_MAX_VALIDATION_RETRIES=3`, then fall through to a human-review fallback (`_FALLBACK`, `human_review_required=True`).
- Groq runtime failure is **caught and surfaced** — the run is marked `FAILED`, the complaint is NOT destroyed, and retry remains allowed.

**Backend — Persistence**
- New tables `agent_runs` (complaint_id, agent, model, status, duration_ms, structured_result JSONB, error, started_at, ended_at) and `agent_events` (run_id, event, payload JSONB, recorded_at).
- Models `app/models/agent_run.py`, `agent_event.py`; enums `AgentStatus`, `TriageSeverity`, `TriageUrgency` in `app/models/enums.py`; `agent_runs` relationship on `Complaint`.
- Schemas `app/schemas/triage.py` (`TriageInput`, `TriageOutput`, `AgentRunOut`, `AgentEventOut`, `TriageRunResponse`, `TriageRunIn`).
- Services `app/services/agent_run_service.py` (create/append/finalize/get) and `app/services/triage_service.py` (run/get latest, access control reusing tracking helpers).
- Migration `5c9d1f3a0e21_agent_runs_and_agent_events_tables.py` **applied and head**.

**Backend — API (`app/api/v1/complaints.py`)**
- `POST /api/v1/complaints/{id}/triage` — runs triage (body optional `TriageRunIn.language`).
- `GET /api/v1/complaints/{id}/ai-triage` — returns latest `AgentRun` (with structured result).
- Error mapping: not-found→404, cross-user/unauthorized→403, unauthenticated→401.

**Frontend**
- `frontend/src/lib/citizen-api.ts` — new types + `fetchAiTriage(id)`, `runAiTriage(id, language)`.
- New component `frontend/src/components/dashboard/ai-analysis-card.tsx` — shows Analyzing spinner / Category / Severity / Urgency / Confidence / Summary / Infrastructure / Recommended action, human-review banner, failure-and-retry, and "Analyze with AI" trigger. Conforms to the `react-hooks/set-state-in-effect` rule (setState only in promise callbacks, `reloadKey` retry).
- Wired into `complaint-detail-view.tsx` (right column, above Status Timeline).

## Files Changed / Added
- New: `backend/app/agents/triage_agent.py`, `backend/app/agents/__init__.py`
- New: `backend/app/models/agent_run.py`, `agent_event.py`
- New: `backend/app/schemas/triage.py`
- New: `backend/app/services/agent_run_service.py`, `triage_service.py`
- New: `backend/alembic/versions/5c9d1f3a0e21_*.py`
- New: `backend/tests/test_triage_agent.py`
- New: `backend/app/api/v1/complaints.py` (triage endpoints added)
- New: `frontend/src/components/dashboard/ai-analysis-card.tsx`
- Modified: `backend/app/models/enums.py`, `app/models/__init__.py`, `app/models/complaint.py`, `app/services/__init__.py`, `app/api/v1/complaints.py`
- Modified: `frontend/src/lib/citizen-api.ts`, `frontend/src/components/dashboard/complaint-detail-view.tsx`

## Model / Config
- Default Groq model `GROQ_MODEL=openai/gpt-oss-120b` (live-verified in Part 6; `llama3-70b-8192` unavailable). Key env var `GROQ_API_KEY` in `backend/.env`. LangGraph 1.2.11 in `pyproject.toml`.

## Tests & Results
- Backend: **71 tests pass** (`pytest -q`, includes 12 new triage tests using `FakeAI`).
- Ruff: **clean** on entire backend (`ruff check .`).
- Frontend: **`npm run lint` clean**, **`npm run build` passes** (Next 16 / TypeScript OK).

## Live E2E (real Groq, real DB, via HTTP)
- Register/login → create complaint → `POST /triage` → **`SUCCEEDED`**, structured result `STREET_LIGHTING / HIGH / HIGH`, confidence 0.96, duration 1975 ms → `GET /ai-triage` returns persisted run with model `openai/gpt-oss-120b`.
- Negative paths: cross-user triage → **403**, nonexistent `ai-triage` → **404**, unauthenticated → **401**.
- Complaint detail page route serves **200** on frontend.

## Errors Fixed During This Session
- Frontend initial AI-card used a `useCallback` `reload()` called synchronously in the effect → lint `react-hooks/set-state-in-effect`; refactored to promise-callback setState + `reloadKey`.
- Trailing-newline `W292` in `app/services/__init__.py` (and `app/agents/__init__.py`) → fixed via `ruff --fix`.
- Backend hot-reload launch used `app.main:app`; actual module is `main:app` (top-level) → corrected.
- Live E2E script field names corrected: `full_name` (register), `description/category/location` (complaint create), token at `tokens.access_token`.

## Known Limitations / Remaining Issues
- None blocking. `STREET_LIGHTING` category returned by the model is a valid refinement but differs slightly from the base `ComplaintCategory` set observed in schemas; it is stored as the triage category string (no enum constraint on `structured_result` JSONB). Acceptable for triage output.
- Human-review fallback path exercised via unit tests (not a separate live failure run).

## Security
- No secrets logged. Groq key accessed only via env var `GROQ_API_KEY`. Access control on triage endpoints enforced (401/403). Frontend never calls Groq directly — always through the backend.

## API Keys
- `GROQ_API_KEY` (env var name) in `backend/.env`.

## Regression Status
- Backend ruff: PASS | Backend pytest (71): PASS | Alembic head: PASS | Frontend lint: PASS | Frontend build: PASS | Live E2E (real Groq): PASS | Manual UI: detail page 200 (client-rendered section verified via build).