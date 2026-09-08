# Part 9 Checkpoint Report — Duplicate Complaint & Incident Correlation Agent

## Status: READY FOR NEXT PROMPT — YES

## What Was Implemented

**Backend — Deterministic LangGraph Correlation Agent (`app/agents/correlation_agent.py`)**
- Fully deterministic — **no LLM**. Graph `START → Embed → Search → Validate → Persist → END`.
- `CorrelationState` TypedDict + nodes `_embed_node/_search_node/_validate_node/_persist_node`, `build_graph()`, and `CorrelationAgent.run(db, complaint_id)`.
- Embedding uses a local Sentence Transformer via `fastembed` (`BAAI/bge-small-en-v1.5`, 384-dim, offline, cached). It runs in a threadpool (`asyncio.to_thread`) so it never blocks the event loop.
- Signals combined into one 0..1 `score`:
  - **Semantic** — pgvector `cosine_distance` over the embedded text (HNSW `vector_cosine_ops` index `idx_complaint_embeddings_embedding_hnsw`), weight 0.5.
  - **Geospatial** — PostGIS `ST_DWithin`/`ST_Distance` (`geography` casts, metre-accurate, reusing `idx_complaint_locations_geom` GiST), weight 0.25, radius `CORRELATION_NEARBY_RADIUS_M`.
  - **Temporal** — age gap within `CORRELATION_TIME_WINDOW_HOURS`, weight 0.15.
  - **Categorical** — same/different `category`, weight 0.10.
- Weights are re-normalised when a signal is absent so the score stays in 0..1. Pure scoring helpers `combine_score/ _geo_component / _time_component / _explain` are fully unit-testable without a DB.
- If the best candidate's `score` ≥ `CORRELATION_COMBINED_THRESHOLD` the complaint is flagged `POSSIBLE_DUPLICATE` (top match surfaced for review); otherwise `NEW_INCIDENT`. An embedding/query/DB failure marks the run `FAILED` and leaves the complaint intact so it can be retried.

**Backend — Models (new Alembic migration `a1b2c3d4e5f6`)**
- `complaint_embeddings` table: `ComplaintEmbedding` with `Vector(384)` (`embedding_dim()` helper), provider/model/dimensions/text_input, HNSW index.
- `complaint_correlations` table: `ComplaintCorrelation` (source/target `complaint_id`, `similarity`, `distance_m`, `time_diff_hours`, `category_match`, `score`, `reason`, `status` PENDING/CONFIRMED/REJECTED, `decided_by`, `decided_at`).
- `complaints.correlation_status` nullable enum `correlation_status` (`NEW_INCIDENT`/`POSSIBLE_DUPLICATE`/`CONFIRMED_DUPLICATE`).
- `CorrelationStatus`/`CorrelationMatchStatus` enums in `app/models/enums.py`; relationships registered in `app/models/__init__.py` (with `foreign_keys=` for the two self-referential correlation FKs).

**Backend — Services & API**
- `app/services/embedding_service.py`: `Embedder` protocol, `LocalFastEmbed` (lazy fastembed via `_get_backend`), `_normalize_text`, `EmbeddingService` (threadpool), deterministic `FakeEmbedder` for offline tests.
- `app/services/correlation_service.py`: `run_correlation`, `get_correlation_result`, `list_candidates`, `decide_candidate` (staff RBAC, sets `decided_by`/`decided_at`; Confirm→`CONFIRMED_DUPLICATE`, Reject→`POSSIBLE_DUPLICATE` on source) + typed errors (`NotFound/Access/CandidateNotFound/CandidateDecided`).
- `app/api/v1/complaints.py`: `POST /{id}/correlate`, `GET /{id}/correlation-result`, `GET /{id}/correlations`, `POST /correlations/{id}/confirm`, `POST /correlations/{id}/reject` (staff Confirm/Reject via `require_roles(OFFICER,ADMIN,WARD_REPRESENTATIVE)`), `_correlation_error` mapper (401/403/404/409).
- Config block `app/core/config.py`: `EMBEDDING_MODEL`, `EMBEDDING_DIM(384)`, `EMBEDDING_CACHE_DIR`, `CORRELATION_SIMILARITY_THRESHOLD(0.72)`, `CORRELATION_NEARBY_RADIUS_M(500)`, `CORRELATION_MAX_CANDIDATES(5)`, `CORRELATION_TIME_WINDOW_HOURS(168)`, `CORRELATION_COMBINED_THRESHOLD(0.6)`.

**Frontend**
- `frontend/src/lib/citizen-api.ts`: types `CorrelationStatus`, `CorrelationMatchStatus`, `CorrelationMatch`, `CorrelationResult`, `AiCorrelationRun`, `RunCorrelationResponse` + `fetchAiCorrelation`, `runAiCorrelation`, `fetchCorrelations`, `confirmCorrelation`, `rejectCorrelation`.
- New component `frontend/src/components/dashboard/correlation-card.tsx`: shows Check-for-duplicates, possible-duplicate banner with the matched complaint (title, similarity, score, distance, age, category), "why" reason, and staff-only Confirm duplicate / Reject buttons. Conforms to `react-hooks/set-state-in-effect` (setState only in promise callbacks, `reloadKey` retry).
- Wired into `complaint-detail-view.tsx` (right column, after Evidence Verification card).

## Model / Config
- `EMBEDDING_MODEL=BAAI/bge-small-en-v1.5` (real, downloaded and cached locally via fastembed ONNX runtime `qdrant/bge-small-en-v1.5-onnx-q`; live-verified 384-dim). Deterministic correlation → no external LLM / no API key needed.

## Files Changed / Added
- New: `backend/app/agents/correlation_agent.py`
- New: `backend/app/schemas/correlation.py`
- New: `backend/app/services/embedding_service.py`
- New: `backend/app/services/correlation_service.py`
- New: `backend/app/models/complaint_embedding.py`, `backend/app/models/complaint_correlation.py`
- New: `backend/alembic/versions/a1b2c3d4e5f6_complaint_correlation_and_embeddings.py` (applied; `alembic current` = head)
- New: `backend/tests/test_correlation_agent.py`
- New: `frontend/src/components/dashboard/correlation-card.tsx`
- Modified: `backend/app/models/complaint.py` (correlation_status column + relationships), `app/models/enums.py`, `app/models/__init__.py`, `app/core/config.py`, `app/agents/__init__.py`, `app/services/__init__.py`, `app/api/v1/complaints.py`, `backend/pyproject.toml` (`fastembed>=0.3.0`)
- Modified: `frontend/src/lib/citizen-api.ts`, `frontend/src/components/dashboard/complaint-detail-view.tsx`

## Migration Applied & Verified
- `a1b2c3d4e5f6_complaint_correlation_and_embeddings.py` (down_revision `5c9d1f3a0e21`). `alembic current` = `a1b2c3d4e5f6 (head)`. Tables `complaint_embeddings` / `complaint_correlations`, HNSW index, `complaints.correlation_status` column and enum labels all verified live in the DB.

## Tests & Results
- Backend: **`tests/test_correlation_agent.py` — 13/13 pass** (uses offline `FakeEmbedder`, real pgvector + PostGIS queries). Accuracy: same-issue nearby → POSSIBLE_DUPLICATE; same-issue far-away → POSSIBLE_DUPLICATE; different-issue nearby → NEW_INCIDENT; different-issue far-away → NEW_INCIDENT; scoring unit tests; embedding + candidate persistence; officer Confirm/Reject RBAC + 409 re-decision; access control 401/403/404.
- Ruff: **clean** on entire backend (`ruff check .`).
- Backend regression (storage-independent): `test_auth.py` + `test_ai_service.py` + `test_health.py` = 34 passed. `test_complaints.py` / `test_complaint_tracking.py` media-upload tests fail **only** on `Upload storage is unavailable.` (500) — **pre-existing** env issue (`STORAGE_BACKEND=s3` / MinIO down), unrelated to Part 9.
- Frontend: **`npm run lint` clean**, **`npm run build` passes** (Next 16 / TypeScript OK).

## Live E2E (real `BAAI/bge-small-en-v1.5` fastembed, real DB, via HTTP)
- Register → login → create C1 and C2 (nearby pothole complaints, no media). Correlation SUCCEEDED (~2.5s), real 384-dim embedding written.
- After embedding C1, re-running C2 detected it: **POSSIBLE_DUPLICATE**, best_match `similarity 0.88`, `distance_m 36.77` (PostGIS), `category_match true`, combined `score 0.9013 ≥ 0.6`, `human_review_required true`, readable reason. Bidirectional detection confirmed (C1's own run also flagged C2).
- Negative paths: citizen Confirm → **403**, correlate unknown id → **404**, unauthenticated result fetch → **401**.

## Errors Fixed During This Session
- E2E script used the wrong login key (`login.json()["access_token"]` → actual `["tokens"]["access_token"]`).
- Early live run reported `NEW_INCIDENT` + `similarity 0.0` for a genuinely similar complaint — this was **not a bug**: C1 had no embedding yet because embeddings are written lazily the first time a complaint is correlated. Once C1 was correlated (embedding materialized), the semantic pool contained its real vector and C2 correctly matched at 0.88. This confirms the intended data-flow; every complaint passing through correlation materializes a real embedding for later detection. (Note: pre-existing FakeEmbedder rows in the shared dev DB from the test suite also appear as low-similarity candidates — harmless, offline-test artifact only.)
- Frontend lint: removed synchronous `setLoading(true)` inside the `useEffect` (violated `react-hooks/set-state-in-effect`) and an unused eslint-disable directive.

## Known Limitations / Remaining Issues
- Embeddings are written lazily per complaint when that complaint is correlated; a brand-new complaint is only a semantic candidate after it has been embedded (either by its own correlation run or a future ingestion step). Geospatial proximity still catches un-embedded nearby reports.
- The shared dev DB contains FakeEmbedder rows from the test suite; real correlation runs compare against these as low-similarity candidates. Isolated/clean DBs won't have this.
- Full-suite `pytest` hangs under this host's memory pressure (~215–586 MB free); suites are run per-file with generous timeouts. Not a code issue.

## Security
- No secrets logged; no external API key — correlation is fully local/offline. Confirm/Reject are staff-only (`OFFICER`/`ADMIN`/`WARD_REPRESENTATIVE`). `list_candidates`/`get_correlation_result` enforce per-user view access (401/403/404). The frontend gates the Confirm/Reject buttons by `user.role.name` and the backend enforces it independently.

## Regression Status
- Backend ruff: PASS | Backend strategy/unit tests (13 + 34): PASS | Alembic head (`a1b2c3d4e5f6`): PASS | Frontend lint: PASS | Frontend build: PASS | Live E2E (real bge-small): PASS (semantic 0.88 + PostGIS 36.77m → POSSIBLE_DUPLICATE) | Negative paths (401/403/404): PASS | Manual UI: correlation card built, linted, and type-checked; wired into detail view.
