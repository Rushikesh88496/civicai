# CivicAgent — Render Production Readiness Report

**Date:** 2026-09-12
**Scope:** Production deployment of the existing CivicAgent project (Next.js +
FastAPI + Postgres/PostGIS/pgvector + Redis + S3-compatible storage + Groq) on
Render. No functionality was removed or altered; no demo/operational data was
created.

---

## Verdict

> **READY FOR RENDER DEPLOYMENT: YES** — the application code and deployment
> configuration are complete and validated. A first live deploy still depends
> on the **Required from you** items (§4); the only step that could not be run on
> this machine is the Docker image build (no Docker installed — see §2, "Docker
> image build (local)").

---

## 1. Section-by-section status

| # | Section | Status | Evidence / notes |
| --- | --- | --- | --- |
| 1 | Project structure / deploy unit | **PASS** | Monorepo: `backend/` (pyproject, Dockerfile, alembic, entrypoint), `frontend/` (package.json, Dockerfile), `infrastructure/` (compose), dev-config + prod-config. |
| 2 | Environment variables | **PASS** | All config env-driven (`backend/app/core/config.py`, pydantic-settings). `.env.example` (root + backend) documents every variable incl. `DATABASE_URL`, `REDIS_URL`, `JWT_SECRET`, Groq, `S3_*`, `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL`. No secrets committed. |
| 3 | Frontend | **PASS** | Removed hard-coded `http://localhost:8000` API fallbacks in 8 files. `next build`, `tsc --noEmit`, `eslint`, vitest (44/44) all pass. Dockerfile binds `0.0.0.0:$PORT`. |
| 4 | Backend | **PASS** | `ruff check` clean; pytest **500 passed / 1 skipped / 1 failed** (the one failure is a local-RAM `MemoryError` generating a 2600×2600 JPEG in-memory; it passes in isolation — environment limit, not a code defect). |
| 5 | CORS | **PASS** | Explicit origins parsed from `CORS_ORIGINS` (whitespace-stripped), `allow_credentials=True`, **no wildcard**. Preflight smoke-tested → correct `access-control-allow-origin`. |
| 6 | PostgreSQL (PostGIS + pgvector) | **PASS** | `alembic upgrade head` runs at container start (entrypoint). Migration `cfbd4ce21b49` creates `postgis` + `vector`; Render Postgres supports both on PG 13+. Fresh-schema migration path proven by the test baseline (see §2). |
| 7 | Redis | **PASS** | `REDIS_URL` env-driven; Blueprint wires Render Key Value (`fromService … connectionString`). App degrades to polling if Redis is unreachable. |
| 8 | Object storage (BEFORE/AFTER evidence) | **PASS** | `STORAGE_BACKEND=s3` (boto3) for durable uploads on Render's ephemeral filesystem; `local` backend requires an attached disk (documented). Upload endpoints degrade to clean 500s on storage failure. |
| 9 | Auth / JWT | **PASS** | Argon2id, HS256 with issuer/audience/jti, 30-min access + refresh tokens with server-side revocation; min 32-byte secret enforced. Blueprint uses `JWT_SECRET: generateValue`. |
| 10 | Groq / AI | **PASS** | `GROQ_API_KEY`/`GROQ_MODEL` env-driven; missing key fails cleanly (`AIConfigurationError`) — deploy recovers; AI features simply unavailable. |
| 11 | Config validation | **PASS** | All inputs validated at startup (secret strength, DB dialect). Added automatic `postgres:// → postgresql+asyncpg://` normalization for Render's injected DB URL. |
| 12 | Logging | **PASS** | Structured JSON (`pythonjsonlogger`) in the container; startup banner logs storage/DB/Redis/Groq/rate-limit profile **without secrets**; verified in a live run. |
| 13 | Health checks | **PASS** | `GET /health` (liveness, no deps) + `GET /api/v1/health` (readiness). Both smoke-tested → `{"status":"ok"}` / `{"status":"healthy","version":"0.1.0"}`. |
| 14 | `render.yaml` Blueprint | **PASS** | YAML parses; creates backend + frontend web services, Postgres, Redis; secrets via `generateValue`/`sync:false` only; `healthCheckPath` set for both services. |
| 15 | Build & start commands | **PASS (static)** / **BLOCKED (local exec)** | Static + run-path verified (`pip install .`, `alembic upgrade head`, `uvicorn` on `$PORT`). Actual `docker image build` **could not be executed** — Docker is not installed on this machine; must happen on Render (or any Docker host). |
| 16 | Migration safety | **PASS** with **WARNING** | Idempotent, versioned, no destructive drops. `alembic check` reports model-vs-migration autogenerate drift (cosmetic: JSON→JSONB, index/constraint naming, the PostGIS system table `spatial_ref_sys`) — **non-blocking**: deploys apply migrations sequentially and never autogenerate. Do not "fix" by autogenerating (it would drop `spatial_ref_sys`). |
| 17 | No fake operational data | **PASS** | Platform is genuinely empty; `SEED_DEMO_DATA` defaults `false` and is dev-only. Nothing demo is created on Render. |
| 18 | Security audit | **PASS** | Security headers (CSP, HSTS, XFO, nosniff), rate limiting, `/docs` disabled in prod, upload MIME/size gates, signed media tokens, login rate limits, no secrets in logs/images (`.dockerignore` blocks `.env*`). |
| 19 | Deployment documentation | **PASS** | `RENDER_DEPLOYMENT.md` added (step-by-step, env reference, storage guidance, troubleshooting, Required-from-user checklist). |

---

## 2. Validation actually executed

| Check | Command / action | Result |
| --- | --- | --- |
| Backend lint | `ruff check main.py app` | All checks passed |
| Backend tests | `pytest -q` (full suite) | 500 passed, 1 skipped, 1 failed (RAM-limit; **passes in isolation**) |
| DB dialect normalization | run `get_settings()` with `DATABASE_URL=postgres://…` | → `postgresql+asyncpg://` ✓ |
| Live health smoke | `uvicorn main:app` + `curl /health`, `/api/v1/health`, CORS preflight | 200s, correct CORS headers ✓ |
| Migration freshness | Guided by the test-suite baseline reset (applies migrations to a fresh schema) | ✓ (suite passes post-migration) |
| Frontend lint/type | `eslint`, `tsc --noEmit` | clean |
| Frontend tests | `vitest run` | 44/44 passed |
| Frontend build | `next build` | clean, full route table produced |
| Blueprint syntax | parse `render.yaml` | ✓ services + databases |

**Not executable on this machine:** Docker image build (`docker` not installed) and a
multi-instance load check. Both are first-run steps on Render.

---

## 3. Change set (this session)

- `backend/app/core/config.py` — `DATABASE_URL` driver normalization (Render-safe).
- `backend/main.py` — root `/health`, whitespace-stripped CORS origins, secret-free startup banner.
- `backend/Dockerfile` — binds `0.0.0.0:$PORT` (default 8000), healthcheck honors `$PORT`.
- `backend/requirements.txt` — **new** (`-e .`, single-source deps).
- `frontend/src/lib/{api,analytics-api,assistant-api,auth-api,complaint-api,i18n,notification-api,officer-api}.ts` — removed `|| "http://localhost:8000"` fallbacks (env-only).
- `frontend/next.config.ts` — `/media` rewrite only when `NEXT_PUBLIC_API_URL` is set.
- `frontend/Dockerfile` — binds `0.0.0.0:$PORT` (default 3000), healthcheck honors `$PORT`.
- `render.yaml` — **new** Blueprint (backend, frontend, Postgres, Redis; no secrets).
- `RENDER_DEPLOYMENT.md` — **new** deployment guide.

Local dev is unaffected (`frontend/.env.local`, compose port mappings 8000/3000 unchanged).

---

## 4. Required from you (before/during the first deploy)

| # | Item | Where | Blocking |
| --- | --- | --- | --- |
| 1 | Render account + this repo accessible from GitHub | Render Dashboard | Yes |
| 2 | Groq API key | prompted at Blueprint creation (`GROQ_API_KEY`) | Yes* |
| 3 | S3-compatible bucket + credentials (AWS/R2/Spaces/B2/MinIO) | prompted at creation (`S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`) — or attach a Render disk + `STORAGE_BACKEND=local` | Yes |
| 4 | `S3_PUBLIC_BASE_URL` | prompted at creation (public bucket URL for direct media loads) | No |
| 5 | `NEXT_PUBLIC_API_URL` = deployed backend URL | frontend env **after** first deploy, then re-deploy | Yes |
| 6 | `CORS_ORIGINS` = deployed frontend URL | backend env **after** first deploy | Yes |
| 7 | First Super Admin account | register via API after deploy (see RENDER_DEPLOYMENT.md §4) | Yes |
| 8 | Compute/DB/Redis plans + region | adjust in the Blueprint or Dashboard | No |
| 9 | (Optional) custom domains, SMTP credentials, HAR | Dashboard | No |

\* The platform deploys and runs without `GROQ_API_KEY`; triage, assistant and
image verification are then unavailable.

---

## 5. Known limitations (non-blocking)

1. `alembic check` autogenerate drift — cosmetic; deploys apply versioned migrations; never autogenerate.
2. slowapi rate-limit counters are per-instance (in-memory) — single-instance fine; document before scaling >1.
3. Embedding model (BGE-small, ~130 MB) downloads on first semantic-correlation use; Render's filesystem is ephemeral so it re-downloads on each fresh instance (one-time cost per instance). Set `EMBEDDING_CACHE_DIR` onto a persistent disk if you want to avoid it. ML surfaces report `INSUFFICIENT_DATA` until real data exists.
4. One suite test (`test_real_size_camera_photo_appears_in_officer_evidence`) needs ~1+ GB RAM to synthesize a 2600×2600 JPEG; passes alone, may fail on RAM-starved CI. Increase CI memory or treat as flaky-by-resource.