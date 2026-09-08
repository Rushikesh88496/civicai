# Part 24 Checkpoint Report - Predictive Infrastructure Maintenance

## Status: READY - YES

## What Was Implemented

**ML pipeline (`app/ml/`)** - a leak-safe predictor for registered municipal assets,
demoed as an officer-facing "AI Prediction" surface (Part 23's hotspot predictor for
complaints; this one for physical infrastructure):
- `infra_features.py` - feature contract + deterministic explainer. Feature vector per
  asset: `age_years` (from `installed_at`), normalized rainfall, complaint count within
  radius (90d) + repair count (12m) over the city, resident-density proxy, one-hot
  `cat_*` per `InfrastructureCategory`, `*_available` flags. Risk buckets via
  `risk_level_for_probability` using configured thresholds
  (`<0.25` LOW, `<0.50` MEDIUM, `<0.75` HIGH, `>=0.75` CRITICAL).
  `recommendation_for` / `supporting_factors_for` / `recommend_action_text` produce
  **"recommended inspection"** wording driven by live factor values - the text never
  claims an asset will fail.
- `infra_corpus.py` - **deterministic** synthetic asset histories (seedable, ends
  2026-09-06): each asset gets a real install date 1-60 years in the past (so the age
  signal is strong and learnable), Poisson complaints/repairs with monsoon-boosted rain,
  and `y_fail` drawn from a probability built directly from the *observable* features
  (age, category base-risk, rain, complaint/repair counts), so XGBoost recovers a
  meaningful ranking (ROC-AUC ~0.65, F1 ~0.62 on held-out).
- `infra_pipeline.py` - `run_infra_training` (time-aware CV with horizon purge, baseline
  rule *risk=1 iff complaints>0 or repairs>0*, XGBoost classifier on the same features,
  joblib bundle round-trip). Where the hotspot pipeline failed to learn its age signal
  during this build, the corpus was redesigned so the model correctly separates LOW /
  HIGH / CRITICAL probes.
- `external.py` - degradable `fetch_infra_citywide_rainfall` (Open-Meteo, weather cache,
  gated by `INFRA_RAINFALL_FETCH`); unavailability degrades to `rainfall_mm=None` flag.

**Models + migration** - four new tables (migration
`alembic/versions/b1c2d3e4f5a6_predictive_infrastructure_maintenance.py` **applied;
head = `b1c2d3e4f5a6`**, chained from Part 23 head `9a8b7c6d5e4f`; native
`sa.Enum` columns consistent with the rest of the schema):
- `infrastructure_assets` - registered assets (name, `InfrastructureCategory`, optional
  ward/lat/lon/address/install date/condition, `is_active`).
- `infrastructure_models` - a **separate registry** from `predictive_models` so an
  infrastructure retrain never deactivates/renumbers the hotspot model. Unique `version`,
  `artifact_filename`, metrics/config JSONB, `is_active`, `trained_by_user_id` FK.
- `infrastructure_predictions` - stored risk outputs: `failure_probability`,
  `InfrastructureRiskLevel`, `recommended_inspection`, `supporting_factors`, `history`,
  `ai_prediction=true`, officer review state (`PENDING`/`APPROVED`/`REJECTED`,
  `reviewed_by`/`reviewed_at`/`review_note`).
- `preventive_work_orders` - optional proactive work orders (no complaint involved, so a
  distinct table with `PreventiveWorkOrderStatus` lifecycle: PENDING_APPROVAL /
  APPROVED / REJECTED / COMPLETED / CANCELLED).

**Service + API (`app/services/infra_service.py`, `app/api/v1/infrastructure.py`,
`app/schemas/infrastructure.py`, registered in `app/api/router.py`)** - prefix
`/api/v1/infrastructure`, city-role gate (OFFICER / ADMIN only; citizens, ward-reps and
field workers 403):
- `GET /status` / `POST /train` - active model + metrics, or "not trained yet";
  retraining offloaded via `asyncio.to_thread`, artifact written to
  `INFRA_ARTIFACT_DIR` (`app/ml/artifacts`), version bumps and deactivates the old row.
- `GET /assets` / `POST /assets` - asset registry list + register.
- `GET /predictions` - **lazy-training** if no active model; live inference over every
  active asset, real complaint/repair history within `INFRA_RADIUS_M` (haversine),
  real weather when enabled; persists one `InfrastructurePrediction` per asset. Response
  explicitly labelled `ai_prediction=true` + disclaimer, `assets_assessed`,
  `horizon_days=30`.
- `POST /predictions/{id}/review` - APPROVED / REJECTED (+ note).
- `POST /predictions/{id}/work-orders` - creates a `PENDING_APPROVAL` preventive work
  order **only** when the prediction is APPROVED (REJECTED/PENDING -> 400).
- Settings added in `app/core/config.py`: `INFRA_ARTIFACT_DIR`, `INFRA_CORPUS_YEARS=2`,
  `INFRA_CORPUS_SEED`, `INFRA_CORPUS_ASSETS=120`, `INFRA_SNAPSHOT_EVERY_DAYS=7`,
  `INFRA_HORIZON_DAYS=30`, `INFRA_TEST_FINAL_DAYS=180`, `INFRA_CV_FOLDS=3`,
  `INFRA_EXTERNAL_DROPOUT=0.25`, `INFRA_RADIUS_M=500`, `INFRA_COMPLAINTS_LOOKBACK_DAYS=90`,
  `INFRA_REPAIRS_LOOKBACK_DAYS=365`, `INFRA_RISK_MEDIUM/HIGH/CRITICAL=0.25/0.50/0.75`,
  `INFRA_RAINFALL_FETCH=False`, `INFRA_N_ESTIMATORS`, `INFRA_MAX_DEPTH`,
  `INFRA_LEARNING_RATE`.

**Seed data (`seed.py`)** - 12 demo infrastructure assets across W-001..W-003 (roads,
bridge, water mains, drainage, sewer, street lighting, park, public buildings) with
install dates spanning 1990-2020 so the demo dashboard shows a realistic mix of
predicted risk; idempotent by (name, category).

**Frontend** - new officer screen styled consistently with hotspots/command center:
- `src/lib/infrastructure-api.ts` - types mirroring the API plus
  `fetchInfrastructureStatus`, `fetchInfrastructurePredictions`, `trainInfrastructureModel`,
  `reviewPrediction`, `createPreventiveWorkOrder`, risk-level badge/color helpers and
  `departmentForCategory` (map asset category -> owning department for work orders).
- `src/components/infrastructure/predictive-infrastructure.tsx` - header with **AI
  Prediction** badge, disclaimer callout, active-model card (AI F1 vs persistence, ROC-AUC,
  mean CV F1) with **Retrain model** button, stats row (assessed / high-critical / pending
  / approved), and a per-asset list: risk badge, predicted-risk probability bar,
  recommended inspection, supporting-factor chips, history (complaints 90d / repairs 12m /
  age). Inline review workflow: Approve / Reject, and after approval a preventive work
  order form (department select pre-filled from category + action text).
- `src/app/officer/infrastructure/page.tsx` (thin server component) + "Predictive
  Maintenance" nav item (Wrench icon) in the officer layout sidebar.

## Tests & Results

- **`tests/test_infrastructure.py` - 11/11 pass** on live dev Postgres: corpus
  determinism (same seed identical, `y_fail` binary); risk-threshold mapping (LOW/MEDIUM/
  HIGH/CRITICAL); recommendation wording **never contains "will fail"** and always
  references inspection; missing-data factors flagged *unavailable/treated-as-none*;
  RBAC (citizen/ward-rep/field-worker 403 on status/train/predictions/assets); retrain
  bumps version + deactivates the previous model (registry row + artifact file);
  missing-data asset still predicts with LOW signal and honest flags; normal quiet asset
  -> LOW with `failure_probability` below the MEDIUM threshold; **high-risk** old asset
  with 12 nearby complaints -> HIGH/CRITICAL with probability >= HIGH threshold and
  complaint-driven factors; lazy-training + stable version across repeated calls +
  disclaimer/`ai_prediction` shape; full review workflow (APPROVE -> 200, work order 201
  PENDING_APPROVAL, invalid decision 422, REJECTED -> work order 400).
- Full backend suite: **323 passed** (312 existing + 11 new) in ~8:37.
- Backend **ruff: clean** (`check app tests`). Alembic at head `b1c2d3e4f5a6`, migration
  applied (enum fix: Part 24 tables were first created with `String` columns in the
  migration while the ORM declared native `Enum`s - corrected to native `sa.Enum`
  columns + downgrade/upgrade round-trip, verified types exist in `pg_type`).
- Frontend: **`tsc --noEmit` clean**, **eslint clean**, **`next build` passes** (25 routes
  incl. `/officer/infrastructure`). `/officer/infrastructure` page -> **HTTP 200** on the
  running dev server.
- Live production smoke (backend restarted to load new code, processes left running on
  :8000 / :3000):
  - `login` officer@example.com -> 200 + token.
  - `GET /api/v1/infrastructure/status` after seed -> `trained=false` (lazy).
  - `GET /api/v1/infrastructure/predictions` -> 200, **lazy-trained v1**, 12 assets
    assessed, `ai_prediction=true`, disclaimer present. Risk distribution across the demo
    assets: Riverside Crossing Bridge CRITICAL 0.79, Riverfront Road Segment HIGH 0.72,
    Riverside Park HIGH 0.70, ... down to Market Street Light Poles LOW 0.23.
  - `POST /predictions/{id}/review` -> 200 APPROVED; `POST /predictions/{id}/work-orders`
    -> **201 PENDING_APPROVAL** (Riverside Crossing Bridge, WATER).
  - Anonymous `GET /status` -> **401**.

## Known Limitations / Notes

- Model is trained on a **deterministic synthetic corpus** (documented in the artifact
  `config.corpus_description`) because the live demo DB has too few repair records and
  assets; **live inference reuses real data** (asset records, complaint history near the
  asset, repairs, weather when enabled) through the identical feature extractor.
- Rainfall provider is disabled by default (`INFRA_RAINFALL_FETCH=False`); enabling it
  switches inference to live Open-Meteo (cached) data and the rainfall signal only turns
  on for assets with coordinates.
- Repair counts are read from real `work_orders` history near the asset; since the demo
  seed creates no historical work orders, most assets predict from complaints + age +
  category, which is why the old, well-complained-about assets dominate the high-risk end.
- Preventive work orders are deliberately a **separate table** from `work_orders` because
  a preventive order has no complaint; the officer approves the model prediction first,
  then raises the order (only an APPROVED prediction accepts one).
- No real maintenance event is implied by a risk score; every payload is labelled
  `ai_prediction` + disclaimer so the UI presents predicted risk and a recommended
  inspection, never a claim that an asset will fail.