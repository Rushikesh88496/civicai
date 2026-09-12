# CivicAgent — Deploy to Render

This guide deploys the CivicAgent backend + frontend as a Blueprint on Render. It
works in lock-step with `render.yaml` at the repo root. Follow it top to bottom —
the **Required from you** checklist at the end lists every value you must supply.

---

## 1. Overview

| Resource | What it is | Port |
| --- | --- | --- |
| `civicagent-backend`  | FastAPI + uvicorn (Docker)        | `$PORT` (Render-injected) |
| `civicagent-frontend` | Next.js (Docker)                  | `$PORT` (Render-injected) |
| `civicagent-postgres` | Render Postgres                    | internal |
| `civicagent-redis`    | Render Key Value (managed Redis)   | internal |

Container images:

* `backend/Dockerfile` — multi-stage; entrypoint `backend/docker/entrypoint.sh`
  waits for PostgreSQL, runs `alembic upgrade head` (idempotent), then launches
  `uvicorn main:app --host 0.0.0.0 --port $PORT`.
* `frontend/Dockerfile` — multi-stage; `next build` embeds `NEXT_PUBLIC_API_URL`
  at build time, then `next start` on `$PORT`.

Both images bind `0.0.0.0:$PORT` and default to their classic ports (8000/3000) so
the existing `docker compose` stacks are unchanged.

---

## 2. Prerequisites

* A GitHub account with this repository pushed (`origin`).
* A Render account.
* A CORS/object store for uploads. Two supported choices:

  * **S3-compatible bucket (recommended for production)** — AWS S3, Cloudflare R2,
    DigitalOcean Spaces, Backblaze B2, or any MinIO-compatible store. Required so
    BEFORE/AFTER evidence images survive restarts. Render containers have an
    **ephemeral** filesystem — every deploy wipes non-bucket storage.
  * **Local storage on a disk** — only if you attach a Render persistent disk to the
    backend and set `STORAGE_BACKEND=local` (see §6). Not durable otherwise.

---

## 3. Deploy (Blueprint)

1. In the Render Dashboard: **New + → Blueprint**.
2. Pick the `civicai` repository (the Blueprint lives at `render.yaml` in the root).
3. Confirm the Blueprint preview. Render will prompt you for every `sync: false`
   variable **once**:
   * `GROQ_API_KEY` (your Groq API key)
   * `S3_ENDPOINT_URL` (e.g. `https://s3.us-east-1.amazonaws.com`, or your R2/Space
     endpoint)
   * `S3_ACCESS_KEY`, `S3_SECRET_KEY`
   * `S3_PUBLIC_BASE_URL` (public origin of your bucket, e.g.
     `https://civicagent-uploads.s3.us-east-1.amazonaws.com`) — optional but
     recommended so browsers load media straight from the store. If you leave it
     empty the API will sign/media-proxy instead.
4. **Create Resources.** Render provisions the Postgres database, Redis, and both
   web services, generating `JWT_SECRET` automatically.
5. Wait for the first build + deploy of both services.

> The first backend deploy runs the schema migration automatically. If the
> database isn't ready yet, `entrypoint.sh` retries for up to ~120 s before the
> orchestrator restarts the container.

---

## 4. Required post-deploy wiring (do NOT skip)

These values can't be known before the services exist, so update them after the
first deploy:

1. Open the **backend** service and read its URL, e.g. `https://civicagent-backend.onrender.com`.
2. Open the **frontend** service → **Environment**:
   * Set `NEXT_PUBLIC_API_URL` to the **backend** URL above, e.g.
     `https://civicagent-backend.onrender.com`.
   * Save — this triggers a rebuild (the value is inlined into the browser bundle).
3. Open the **backend** service → **Environment**:
   * Set `CORS_ORIGINS` to the **frontend** URL, e.g.
     `https://civicagent-frontend.onrender.com` (comma-separated if you add custom
     domains later: `https://app.example.com,https://www.example.com`).
   * Save.
4. (Optional) Create the first Super Admin account:
   ```
   # registers the first SUPER_ADMIN; subsequent admins are invited by the panel
   curl -X POST https://civicagent-backend.onrender.com/api/v1/auth/register \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@example.com","password":"<STRONG_PASSWORD>","full_name":"City Admin"}'
   ```
   Do **not** enable demo/seeding anywhere on Render.

---

## 5. Health checks & monitoring

* Backend liveness: `GET /health` (no dependencies — orchestrator probe) — set as
  `healthCheckPath` in `render.yaml`.
* Backend readiness: `GET /api/v1/health` (reports DB/Redis/storage/AI status and a
  device code).
* Frontend probe: `GET /` — set as `healthCheckPath`.
* If a container reports unhealthy, Render restarts it; check **Logs** → structured
  JSON lines. The startup banner logs (without secrets):
  `environment`, `storage`, `database_host`, `redis_host`, `groq_configured`,
  `rate_limit_enabled`.

---

## 6. Object storage (evidence persistence)

Set `STORAGE_BACKEND=s3` in `render.yaml` (already defaulted). Backend URL builder:

* With `S3_PUBLIC_BASE_URL` set, stored objects get absolute S3 URLs and browser
  media tags load them directly off the bucket (works if the bucket is public-read).
* Without it, media is proxied/signed through the API instead.

**Local uploads on Render are NOT durable.** If you prefer `STORAGE_BACKEND=local`,
you must attach a disk to the backend service in the Dashboard
(**Disks** → Add Disk → mount at `/app/uploads`, size ≥ 1 GB) and set
`STORAGE_LOCAL_DIR=/app/uploads`. Restarting/redploying without a disk deletes
uploads.

---

## 7. Environment variable reference

| Variable | Required ? | Default | Notes |
| --- | --- | --- | --- |
| `DATABASE_URL` | yes | localhost dev | Injected by Blueprint (`fromDatabase`). Plain `postgresql://` is auto-converted to `postgresql+asyncpg://` by `config.py`. |
| `REDIS_URL` | no | localhost | Injected from the Key Value service. App degrades gracefully (polling) if missing. |
| `JWT_SECRET` | yes | — | `generateValue` in Blueprint; min 32 bytes enforced at startup. |
| `DEBUG` | no | `false` | Must stay `false` in production (disables `/docs`, enables security headers). |
| `GROQ_API_KEY` | yes (for AI/vision) | — | Prompted at Blueprint creation. Services degrade gracefully when unset. |
| `GROQ_MODEL` | no | `openai/gpt-oss-120b` | Any active Groq chat model. |
| `VISION_MODEL` | no | `qwen/qwen3.6-27b` | Multimodal model for image evidence + verification. |
| `STORAGE_BACKEND` | yes | `local` | `s3` recommended on Render. |
| `STORAGE_BUCKET` | no | `civicagent-uploads` | Bucket name. |
| `S3_ENDPOINT_URL` | yes (s3) | localhost MinIO URL | e.g. `https://s3.us-east-1.amazonaws.com`. |
| `S3_ACCESS_KEY` / `S3_SECRET_KEY` | yes (s3) | — | Bucket credentials. |
| `S3_REGION` | no | `us-east-1` | |
| `S3_SECURE` | no | `false` | `true` → HTTPS endpoint. |
| `S3_PUBLIC_BASE_URL` | no | — | Public bucket URL for direct media loading. |
| `CORS_ORIGINS` | yes | `http://localhost:3000` | Production = frontend origin(s), comma-separated, **no `*`** (credentials are used). |
| `EMAIL_PROVIDER` | no | `console` | `console` logs only; set `smtp` + `SMTP_*` to send real mail. |
| `SEED_DEMO_DATA` | — | `false` | Never set `true` outside local/demo environments. |

All backend settings live in `backend/app/core/config.py` (pydantic-settings, env
= field names). No application code change is required to reconfigure.

---

## 8. Database migrations

* Migration tool: Alembic (`backend/alembic/`), run automatically at container start.
* PostGIS + pgvector: migration `cfbd4ce21b49` runs
  `CREATE EXTENSION IF NOT EXISTS postgis` and `CREATE EXTENSION IF NOT EXISTS "vector"`.
  Render Postgres supports both on PostgreSQL 13+ — no manual step.
* Migrations are sequential and idempotent; redeploys are no-ops.

---

## 9. Local parity

The same images/config run locally:

```
docker compose -f infrastructure/docker-compose.yml up --build
```

$PORT Dockerfiles mean the compose port mappings (8000/3000) are unchanged. CI
(GitHub Actions: lint, typecheck, backend + frontend tests, build) runs on every
push.

---

## 10. Troubleshooting

| Symptom | Likely cause / fix |
| --- | --- |
| Backend restarts at first deploy | Postgres still provisioning — entrypoint waits ~120 s, then Render restarts. Reduce by provisioning DB before services, or just wait. |
| `JWT_SECRET` validation error | `JWT_SECRET` shorter than 32 bytes. Regenerate. |
| Frontend shows `ECONNREFUSED /api` | `NEXT_PUBLIC_API_URL` still `http://localhost:8000`. Update + rebuild (§4). |
| Browser CORS errors | `CORS_ORIGINS` must contain the exact frontend origin incl. scheme + port (`https://…onrender.com`, no trailing slash). |
| Uploads succeed but images 404 after redeploy | Local storage without a disk — evidence lost. Switch to `STORAGE_BACKEND=s3`. |
| Login works, realtime chat silent | Redis unreachable — verify `REDIS_URL` fromService pointed at Key Value (`redis://red-…`). App falls back to polling. |
| AI says "AI is not configured" | `GROQ_API_KEY` missing or model not active on the account. |

---

## Required from you

| # | Item | Where | Blocking? |
| --- | --- | --- | --- |
| 1 | Render account + GitHub repo access | Render Dashboard | Yes |
| 2 | Groq API key | prompted at Blueprint creation (`GROQ_API_KEY`) | Yes* |
| 3 | S3-compatible bucket + credentials | prompted at creation (`S3_ENDPOINT_URL`, `S3_ACCESS_KEY`, `S3_SECRET_KEY`) — or attach a disk for local storage | Yes |
| 4 | `NEXT_PUBLIC_API_URL` = deployed backend URL | frontend env, after first deploy, then rebuild | Yes |
| 5 | `CORS_ORIGINS` = deployed frontend URL | backend env, after first deploy | Yes |
| 6 | First Super Admin account | register via API (§4 step 4) | Yes |
| 7 | (Optional) plans/regions/HAR | adjust to your budget | No |
| 8 | (Optional) custom domains | Dashboard → service → Settings | No |
| 9 | (Optional) SMTP credentials for email notifications | backend env | No |

* Without `GROQ_API_KEY` the platform deploys and runs, but triage, the assistant,
and image verification are unavailable.