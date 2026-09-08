# Part 23 Checkpoint Report - Predictive Civic Hotspots

## Status: READY - YES

## What Was Implemented

**ML pipeline (`app/ml/`)** - an end-to-end, leak-safe predictor demoed as an
officer-facing "AI Prediction" surface:
- `grid.py` - `HotspotGrid` over the demo city bbox `17.40,78.35-17.50,78.49` at
  0.01 deg cells (15x11 = **165 cells**), id `r{row}c{col}`, deterministic 4-connectivity
  neighbors, oob -> `None`.
- `corpus.py` - **deterministic** synthetic historical corpus (seedable, ends 2026-09-06),
  monsoon-boosted seasonal rates, Knuth-poisson daily draws, 10 complaint categories.
- `features.py` - structural leakage controls (unit-tested): trailing features use only
  events *strictly before* `d` (`shift(1)` before rolling); labels use only `(d, d+7]`.
  28 numeric features + `cell_id` categorical (XGBoost `enable_categorical`): cell
  coords, trailing 1/7/14/28d + neighbor 14/28d + per-category 14d counts, calendar
  (doy/weekday sin+cos, month, weekend, monsoon) + external (rain, population, infra).
  Also fixes the numpy-2 floor-division depreciation (`//` -> `/`) and adds dtype
  narrowing (`.astype(int)`) helpers.
- `external.py` - degradable providers (never raise): citywide rainfall via Open-Meteo
  (cached with weather cache helpers, gated by `HOTSPOT_RAINFALL_FETCH`), population
  proxy (residents per ward), infra age; `LiveContextProvider` for inference.
- `pipeline.py` - `run_training` (time-aware expanding-window CV with horizon purge gap,
  held-out final `HOTSPOT_TEST_FINAL_DAYS`, external-dropout masking so the model can't
  over-rely on providers, persistence baseline `trail14>0`, clf/reg metric sets),
  `_fit_pair` (XGBoost classifier w/ `scale_pos_weight` + regressor), joblib bundle
  round-trip, `predict_from_bundle`.

**Registry + migration** - `app/models/predictive_model.py` (`predictive_models`:
unique `version`, `kind`, `artifact_filename`, metrics/config JSONB, `is_active`,
`trained_by_user_id` FK users RESTRICT, `trained_at`; exactly one active - retraining
deactivates the old row). Migration
`alembic/versions/9a8b7c6d5e4f_predictive_hotspot_models.py` **applied; head = `9a8b7c6d5e4f`**
(chained from Part 22 head `8f4e9d2c1b0a`).

**API (`app/api/v1/hotspots.py`, `app/services/hotspot_service.py`,
`app/schemas/hotspots.py`)** - prefix `/api/v1/hotspots`, city-role gate
(OFFICER / ADMIN only; citizens, ward-reps and field workers 403):
- `GET /status` - active model + metrics, or "not trained yet".
- `POST /train` - retrain on the deterministic corpus (CPU-bound work offloaded via
  `asyncio.to_thread`), writes `app/ml/artifacts/hotspot_v{N}.joblib` (joblib compress=3),
  bumps version, deactivates the previous active model.
- `GET /predictions` - **lazy-training** if no active model yet; live inference on real
  complaints (last 30 days joined to `complaint_locations` -> grid cells), same feature
  extractor as training, cell->ward via PostGIS `find_ward`, observed trailing-7 context.
  Response is **explicitly labelled**: `ai_prediction=true`, a disclaimer carrying the
  word "forecast", `risk_score` = P(>=1 new complaint in next `horizon`), `expected_volume`
  (clipped >=0), tier high>=0.5 / medium>=0.25 / low, per-cell ward + observed trailing7.
- Settings added in `app/core/config.py`: `HOTSPOT_CELL_DEG=0.01`,
  `HOTSPOT_BBOX="17.40,78.35,17.50,78.49"`, `HOTSPOT_HORIZON_DAYS=7`,
  `HOTSPOT_CORPUS_YEARS=2`, `HOTSPOT_CORPUS_SEED=20260906`, `HOTSPOT_SNAPSHOT_EVERY_DAYS=2`,
  `HOTSPOT_TEST_FINAL_DAYS=180`, `HOTSPOT_CV_FOLDS=3`, `HOTSPOT_EXTERNAL_DROPOUT=0.25`,
  `HOTSPOT_ARTIFACT_DIR="app/ml/artifacts"`, `HOTSPOT_RAINFALL_FETCH=False`,
  `HOTSPOT_N_ESTIMATORS=300`, `HOTSPOT_MAX_DEPTH=6`, `HOTSPOT_LEARNING_RATE=0.05`.

**Frontend** - new officer screen styled consistently with command center/analytics:
- `src/lib/hotspot-api.ts` - types mirroring the API + `fetchHotspotStatus`,
  `fetchHotspotPredictions`, `trainHotspotModel` (shared token machinery from `auth-api`).
- `src/components/hotspots/predictive-hotspot-map.tsx` + `-canvas.tsx` - Leaflet (plain,
  `next/dynamic ssr:false`) grid overlay: rectangles colored by risk tier (high red /
  medium amber / low green), click popup with probability, expected volume, ward and
  observed 7d, auto-fit bounds, in-map legend titled **AI-predicted risk**.
- `src/components/hotspots/predictive-hotspots.tsx` - header with explicit **AI
  Prediction** badge, full disclaimer callout, active-model card (AI F1 vs persistence
  baseline, ROC-AUC, best F1 @ threshold, MAE, CV mean F1) with **Retrain model** button,
  risk map card, high/medium/complaint counts, top-10 hotspot table with tier badges.
- `src/app/officer/hotspots/page.tsx` (thin server component) + "Predictive Hotspots"
  nav item in the officer layout sidebar.

## Tests & Results

- **`tests/test_hotspots.py` - 10/10 pass** on live dev Postgres: grid geometry + replay
  idempotence; feature extractor leak-freedom (same-day event excluded from features,
  labels strictly `(d, d+7]`, span-every-cell); corpus determinism (same seed identical,
  different seed differs); provider degradation (rain/population unavailable -> flags, no
  raise); RBAC (citizen/ward-rep/field-worker 403 on all three endpoints); training writes
  artifact + registry row and version bump deactivates the previous model; predictions
  lazy-train and carry the AI disclaimer.
- Full backend suite: **312 passed** (302 existing + 10 new) in ~8:34.
- Backend **ruff: clean** (`check app tests`). Alembic at head `9a8b7c6d5e4f`, migration
  applied. `seed.py` re-run after the suite to restore demo data.
- Frontend: **`tsc --noEmit` clean**, **eslint clean**, **`next build` passes** (24 routes
  incl. `/officer/hotspots`).
- Live production smoke (servers restarted, left running on :8000 / :3000):
  - `GET /api/v1/hotspots/status` after seed 200 + `trained=false`.
  - `GET /api/v1/hotspots/predictions` -> 200, **lazy-trained v1 in ~59s**, 165 cells
    (sorted risk desc), `ai_prediction=true`, disclaimer contains "forecast", horizon 7,
    `complaint_events_used=7`, `population_cells=48`; representative cell r3c4
    risk 0.9578 (high) vol 2.664 ward W-002.
  - `POST /train` -> **v2** in ~54s (57,255 training rows), active; status shows v2 active;
    citizen `GET /predictions` -> **403**.
  - `/officer/hotspots` page -> **HTTP 200**.

## Known Limitations / Notes

- Model is trained on a **deterministic synthetic corpus** (documented in the artifact
  `config.corpus_description`) because the live demo DB has too few complaints; **live
  inference reuses real complaints** through the identical feature extractor.
- At the current calendar period (monsoon month), the classifier outputs a high
  proportion of high-risk cells; this is a fidelity characteristic of the synthetic
  training data, not an error - the risk gradient and expected volumes still rank cells.
- Rainfall provider is disabled in the default config (`HOTSPOT_RAINFALL_FETCH=False`);
  enabling it switches inference to live Open-Meteo (cached) data.
- No real citizen of the risk-map forecast is implied; every payload is labelled
  `ai_prediction` + disclaimer so the UI cannot present a forecast as confirmed incidents.