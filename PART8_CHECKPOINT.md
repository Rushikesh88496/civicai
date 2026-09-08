# Part 8 Checkpoint Report — Multimodal Vision (Evidence Verification) Agent

## Status: READY FOR NEXT PROMPT — YES

## What Was Implemented

**Backend — LangGraph Vision Agent (`app/agents/vision_agent.py`)**
- Graph `START → Vision → Validate → Persist → END` with conditional edges `{"vision","persist","fail","retry"}`.
- `VisionState` TypedDict and nodes `_vision_node/_validate_node/_persist_node`, `build_graph()`, and `VisionAgent.run(db, complaint_id, input_data)` orchestrator.
- Uses the centralized Groq `AIService` (Part 6) via the new `structured_vision_completion()` — OpenAI-style `content` arrays with base64 `image_url` parts, `response_format=json_object`, max 5 images/request, 2048 tokens/image.
- Flow: load images from storage → build content array with `VISION_MODEL` → structured `VisionOutput` (all 7 spec fields) → validate (mismatch or confidence < 0.5 forces human review → copy output with `human_review_required=True`) → persist run + transition complaint to `EVIDENCE_VERIFIED` (never closed). Any image/provider/parser failure marks the run `FAILED`, preserves the complaint, and allows retry; after retries are exhausted a `_FALLBACK` (conf 0.0, `human_review_required=True`) is persisted.

**Backend — Storage**
- `Storage.read(key) -> bytes` added to `app/storage/base.py` (abstract), implemented in `local.py` (reads bytes; missing file raises `FileNotFoundError`) and `s3.py` (`get_object(...).Body.read()`).

**Backend — Persistence**
- Reuses existing `agent_runs`/`agent_events` tables with `agent="vision"` and JSONB `structured_result` — **no new migration** (head stays `5c9d1f3a0e21`).
- Generalized `app/services/agent_run_service.py`: `create_run`/`finalize_run` now accept `BaseModel | dict | None` via a new `_result_to_dict()` (backward-compatible with triage).
- New `app/schemas/vision.py`: `VisionInput`, `VisionOutput`, `VisionRunOut`, `VisionRunResponse`, `VisionRunIn`.
- New `app/services/vision_service.py`: `run_vision`/`get_vision_result`/`_image_keys` (filters to `media_type == IMAGE`, ordered by created_at) + access control via `user_can_view` (`VisionNotFoundError`/`VisionAccessError`).
- `app/agents/__init__.py` rewritten with aliased exports (`TRIAGE_*` / `VISION_*`) avoiding name collisions.

**Backend — Configured Vision**
- `app/core/config.py`: `VISION_PROVIDER="groq"` (only provider supported; reuses `GROQ_API_KEY`), `VISION_MODEL="qwen/qwen3.6-27b"`, `VISION_MAX_IMAGE_MB=10`, `VISION_TIMEOUT_SECONDS=60.0`. Documented in `backend/.env.example`.

**Backend — API (`app/api/v1/complaints.py`)**
- `POST /api/v1/complaints/{id}/vision` — runs the vision agent (empty body allowed; `VisionRunIn | None`).
- `GET /api/v1/complaints/{id}/vision-result` — returns the latest `AgentRun` (`VisionRunOut`).
- Error mapping via `_vision_error`: not-found→404, cross-user/unauthorized→403, unauthenticated→401, provider/other→400.

**Frontend**
- `frontend/src/lib/citizen-api.ts` — new types (`VisionResult`, `AiVisionRun`, `RunVisionResponse`) + `fetchAiVision(id)`, `runAiVision(id)`.
- New component `frontend/src/components/dashboard/evidence-verification-card.tsx` — shows the first attached image, Evidence detected / No matching evidence badge, Severity, Confidence, Detected issue, Mismatch flag, Evidence explanation, human-review banner, model label, and Verify-with-AI / Retry actions. Conforms to `react-hooks/set-state-in-effect`: setState only in promise callbacks, `reloadKey` retry.
- Wired into `complaint-detail-view.tsx` (right column, after AI Analysis card).

## Files Changed / Added
- New: `backend/app/agents/vision_agent.py`
- New: `backend/app/schemas/vision.py`
- New: `backend/app/services/vision_service.py`
- New: `backend/tests/test_vision_agent.py`
- New: `backend/scripts/e2e_vision.py` (live E2E harness)
- New: `frontend/src/components/dashboard/evidence-verification-card.tsx`
- Modified: `backend/app/services/ai_service.py` (`structured_vision_completion`), `app/services/agent_run_service.py` (`_result_to_dict`), `app/core/config.py` (vision settings), `app/storage/base.py`+`local.py`+`s3.py` (`read()`), `app/agents/__init__.py` (aliased exports), `app/api/v1/complaints.py` (vision endpoints), `backend/.env.example`
- Modified: `frontend/src/lib/citizen-api.ts`, `frontend/src/components/dashboard/complaint-detail-view.tsx`
- **No migration** added; Alembic head unchanged at `5c9d1f3a0e21`.

## Model / Config
- `VISION_MODEL=qwen/qwen3.6-27b` (live-verified Groq multimodal model, shared `GROQ_API_KEY`). `VISION_PROVIDER=groq`. Text model unchanged `GROQ_MODEL=openai/gpt-oss-120b`.

## Tests & Results
- Backend: **83 tests pass** (`pytest -q`; 71 prior + 12 new vision tests using `FakeAI` for `structured_vision_completion`). Scenarios: pothole (evidence detected), water leak, unrelated image (mismatch→human review), low confidence (forces review even if model didn't), invalid image bytes (FAILED), missing image (FAILED "No image"), non-image/video-only (FAILED), Groq failure (FAILED + preserved, retry succeeds on 2nd run), missing API key (FAILED "GROQ"), API run+result, 401, 403, 404.
- Ruff: **clean** on entire backend (`ruff check .`).
- Frontend: **`npm run lint` clean**, **`npm run build` passes** (Next 16 / TypeScript OK).

## Live E2E (real Groq `qwen/qwen3.6-27b`, real DB, via HTTP)
- Register → upload pothole image → create complaint → `POST /vision` → **`SUCCEEDED`**, `visual_evidence_detected=True`, confidence 0.85–0.9, severity MEDIUM, `evidence_description` correctly named a pothole; `GET /vision-result` returns `agent=vision`, `model=qwen/qwen3.6-27b`, all 7 `structured_result` fields → complaint advanced to `EVIDENCE_VERIFIED`.
- Unrelated (sky) image → `SUCCEEDED` with `mismatch_detected=True` + `human_review_required=True` (routed for review, **not closed**).
- Negative paths: unauthenticated → **401**, cross-user → **403**, missing complaint → **404**.
- Detail page route serves **200** on the frontend dev server.

## Errors Fixed During This Session
- Removed an unused `MediaType` import in `vision_agent.py` (ruff F401).
- `_validate_node` did not persist `human_review_required=True` on the output for mismatch/low-confidence results — added `output.model_copy(update={"human_review_required": True})` so the stored result matches the human-review routing.
- Test helper `_storage_keys` returned all media; filtered to `media_type == IMAGE` (mirroring `vision_service._image_keys`) so video-only complaints hit the "No image" failure path, not an invalid-image error.
- Multiple ruff E501/I001/W292 (long import/service lines, import sorting `__init__.py`, trailing newlines) fixed via `ruff --fix`.
- E2E cleanup used a nonexistent `DELETE /auth/me`; replaced with direct DB deletion via `async_session_factory`.
- Backend `--reload` watch picked up the new `scripts/e2e_vision.py` and reloaded; port 8000 was briefly a stale LISTEN artifact — rebinding a fresh uvicorn on 8000 succeeded (frontend default target kept healthy).

## Known Limitations / Remaining Issues
- `detected_issue` can be an empty string in some model responses; the schema allows it and the UI renders “—”. Not blocking.
- The `scripts/e2e_vision.py` is a manual harness (not collected by pytest); it depends on a live `GROQ_API_KEY` and a running server, so it is intentionally excluded from the suite.
- Human-review fallback after exhausting retries is covered by unit tests but was not driven to a live failure run.

## Security
- No secrets logged. Groq key accessed only via env var `GROQ_API_KEY`. Vision endpoints enforce access control (401/403/404). The frontend never calls Groq directly — always through the backend; images are read server-side from storage and never leak the API key. A vision run never closes a complaint.

## API Keys
- `GROQ_API_KEY` (env var name) in `backend/.env`. Vision reuses the same key; `VISION_MODEL=qwen/qwen3.6-27b` (note: "Qwen2.5-VL" is NOT served by Groq).

## Regression Status
- Backend ruff: PASS | Backend pytest (83): PASS | Alembic head (`5c9d1f3a0e21`): PASS | Frontend lint: PASS | Frontend build: PASS | Live E2E (real Groq vision): PASS | Negative paths (401/403/404): PASS | Manual UI: detail page 200, client-rendered card verified via build & API contract.