# CivicAgent

> An intelligent civic-governance platform that carries a citizen complaint from
> submission to verified resolution: AI analysis of evidence, context enrichment,
> duplicate detection, deterministic priority scoring, department routing,
> field-work dispatch, and vision-assisted repair verification — with a human
> officer accountable at every decision point.

CivicAgent is a full-stack civic-complaint management system. A citizen reports
an issue with photos and GPS; the pipeline analyzes the evidence, enriches it
with weather / GIS / historical context, detects near-duplicate reports, assigns
a priority, routes the case to the correct municipality department, dispatches a
field worker, verifies the finished repair with a vision model, and closes the
loop with the citizen.

**Try it:** interactive API documentation (`/docs`) is available when the backend
runs with `DEBUG=true`; the Compose stack ships with demo login accounts (see
[Demo Workflow](#demo-workflow)).

## Table of Contents

- [Highlights](#highlights)
- [Who It's For](#whos-it-for)
- [Closed-Loop Resolution Pipeline](#closed-loop-resolution-pipeline)
- [Intelligence Architecture](#intelligence-architecture)
- [Role-Based Access & Ward Isolation](#role-based-access--ward-isolation)
- [Tech Stack](#tech-stack)
- [Repository Layout](#repository-layout)
- [Backend API](#backend-api)
- [Data & Database](#data--database)
- [Security & Governance](#security--governance)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [AI / LLM Setup](#ai--llm-setup)
- [Storage](#storage)
- [Testing & CI](#testing--ci)
- [Demo Workflow](#demo-workflow)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)

## Highlights

- **Citizen portal** — complaint submission with photos, video, GPS or map pin;
  live status timeline; messaging with the ward office; resolution ratings; and
  an AI assistant that answers in multiple languages from the official
  knowledge base.
- **Officer / Command Center** — live geospatial map, priority dashboard,
  complaint threads, dispatch control, routing overrides, repair verification,
  SLA tracking, analytics, and predictive hotspot / infrastructure-risk
  forecasts.
- **Field-worker workbench** — a mobile-first job flow that works offline
  (local evidence queue with automatic sync when connectivity returns):
  accept → check-in → start → finish → evidence upload.
- **Ward representatives** — ward-scoped triage queue, citizen relationships,
  and ward analytics.
- **Deterministic decisioning** — priorities and department routing are scored
  with weighted, explainable rules; the LLM **never** sets numeric scores or
  chooses departments.
- **Human-in-the-loop** — officers own decisions, and P1-critical verifications
  always require an authorized human sign-off before a high-confidence AI
  verdict is accepted.
- **Governance** — every agent run and decision is recorded for audit; an SLA
  policy engine enforces service-level targets; full activity and status
  history is retained.

## Who It's For

| Role | Portal | What they do |
| --- | --- | --- |
| Citizen | Citizen portal | Report issues (text + photos + GPS), track status live, message the ward office, rate the resolution, ask the AI assistant |
| Officer | Command Center | Oversee the pipeline, review AI analysis, verify evidence, dispatch, override routing, approve critical closures |
| Field Worker | Field workbench | Execute assigned work orders; works offline with deferred evidence sync |
| Ward Rep | Ward portal | Review ward triage, engage citizens, monitor ward analytics |
| Admin | Admin panel | Users, roles, departments, SLA policies, ML and system configuration |

## Closed-Loop Resolution Pipeline

```text
 Citizen submission (text + photos + video + GPS / map pin)
      │
      ▼
 Ingestion & validation ─── media upload (local disk or S3/MinIO)
      │                      signed-HMAC media URLs, size & type limits
      ▼
 AI Triage & Classification ── vision analysis of photos (VISION_MODEL)
      │                        category + subcategory, multilingual text
      ▼
 Context Enrichment ──────── reverse geocode (Nominatim), weather
      │                       (Open-Meteo), nearby critical infrastructure,
      │                       historical volume in the ward
      ▼
 Duplicate / correlation ─── semantic embeddings (fastembed, offline)
      │                       + PostGIS distance + time window
      ▼
 Priority Engine ─────────── deterministic weighted score → P1..P4
      ▼
 Department Routing ──────── deterministic rules → one of seven departments
      ▼
 Work Order + Dispatch ───── scored candidate workers (availability, skill,
      │                       distance, workload, equipment, ward, priority)
      ▼
 Field execution ─────────── accept → check-in → start → finish → evidence
      ▼
 Resolution verification ─── BEFORE/AFTER vision comparison + confidence
      │                       floors; P1-critical requires human sign-off
      ▼
 Citizen closure ─────────── status updates, rating, SLA outcome
```

## Intelligence Architecture

Every step is a small, named agent that writes its run/events to the governance
tables; several are orchestrated with **LangGraph**. The AI-facing providers
(Groq for chat + vision, Open-Meteo for weather, Nominatim for reverse
geocoding) are all externally configured with timeouts, retries and graceful
degradation.

| Agent / Engine | Role | Determinism |
| --- | --- | --- |
| Vision agent | Extracts damage/fault facts from citizen photos | LLM (vision), sandboxed |
| Triage & Classification | Category + subcategory from text/photos | LLM |
| Correlation agent | Links probable duplicate / related complaints | Rule + embeddings, deterministic flag |
| Context agent | Weather, reverse-geocoded address, nearby critical infra, ward history | External APIs, cached in Redis |
| Priority engine | Weighted 0–100 score → P1_CRITICAL … P4_LOW | Fully deterministic |
| Routing engine | Maps category to the responsible department (+ optional secondary) | Fully deterministic |
| Dispatch engine | Scores candidate field workers per order | Fully deterministic |
| SLA engine | Applies SLA policies to work orders | Rules |
| Repair-verification agent | Compares BEFORE/AFTER evidence against the complaint | LLM (vision) + confidence floors |
| Classification service | ML-classify history for analytics/assistant | Model |
| Hotspot / Infra pipelines | Trains XGBoost forecasts on **real** data accumulation | Gated by data volume |

Priority buckets (`PRIORITY_THRESHOLD_*`): `[80,100] → P1_CRITICAL`,
`[60,80) → P2_HIGH`, `[40,60) → P3_MEDIUM`, `[0,40) → P4_LOW`. The seven routing
departments are `WATER, ROADS, ELECTRICAL, WASTE, DRAINAGE, PARKS,
EMERGENCY_DISASTER`.

## Role-Based Access & Ward Isolation

- API authorization uses **JWT bearer tokens** (HS256, 30-minute access +
  7-day refresh with server-side revocation; Argon2id password hashing).
- Roles: `CITIZEN`, `FIELD_WORKER`, `WARD_REP`, `OFFICER`, `ADMIN`.
- Field workers are scoped to their home ward; ward reps to their ward; citizens
  to their own complaints. Geolocation and work-order activity carry GPS
  accuracy data for audit.
- Uploaded media is served through short-lived **HMAC-signed** URLs, never
  anonymous; every local `/media` request without a valid token is rejected.

## Tech Stack

| Layer | Technology |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript 5, Tailwind CSS 4, Leaflet maps, Vitest |
| Backend | Python ≥3.11, FastAPI, Pydantic v2, SQLAlchemy 2 (async), Alembic, LangGraph ≥1.2 |
| Database | PostgreSQL (Compose: postgis `16-3.4`; local reference: 17) with PostGIS + pgvector |
| Cache / realtime | Redis (pub/sub for notifications, external-API response cache) |
| AI / LLM | Groq (chat + vision), fastembed (offline embeddings), scikit-learn / XGBoost |
| Storage | Local disk or S3 / MinIO-compatible object storage (boto3) |
| Containerization | Docker + Docker Compose (dev / test / minio profiles) |
| CI | GitHub Actions — lint, typecheck, unit tests, build |

## Repository Layout

```text
civicai/
├── .github/workflows/        # CI (backend-tests, frontend-tests, lint, typecheck, build)
├── backend/
│   ├── app/
│   │   ├── agents/           # Context, triage, priority, routing, dispatch, SLA, correlation,
│   │   │                     # vision, verify-repair agents
│   │   ├── api/v1/           # FastAPI routers (auth, complaints, work_orders, geo, analytics, …)
│   │   ├── core/             # Settings, security (JWT/Argon2id), Redis, realtime, vault
│   │   ├── db/               # Async session, models
│   │   ├── ml/               # Hotspot + infrastructure pipelines, readiness gating, grids
│   │   ├── schemas/          # Pydantic v2 request/response models
│   │   ├── services/         # Domain logic (complaint, dispatch, verification, admin, …)
│   │   ├── storage/          # Local + S3/MinIO backends
│   │   └── middleware/       # Security headers, rate limiting
│   ├── alembic/versions/     # Migrations (PostGIS/pgvector, identity, SLAs, ML tables, …)
│   ├── tests/                # Backend pytest suite
│   ├── seed.py               # Reference-only demo seed (platform ships empty)
│   ├── main.py               # FastAPI entry point
│   └── pyproject.toml        # Backend dependencies + dev tooling (ruff)
├── frontend/
│   ├── src/app/              # Citizen, officer, work, ward-rep portals; auth, about
│   ├── src/components/       # UI + role-specific components
│   ├── src/lib/              # API clients, offline evidence queue, i18n, roles
│   ├── src/hooks/            # Geolocation, notifications
│   └── package.json          # Next 16, React 19, Vitest, ESLint, tsc
├── infrastructure/
│   ├── docker-compose.yml    # frontend + backend + postgres + redis
│   ├── docker-compose{,.dev,.test,.minio,.postgres}.yml
│   └── init.sql              # PostGIS + pgvector
├── docs/                     # architecture.md, database.md, development.md
└── .env.example              # Full environment reference
```

## Backend API

All endpoints are mounted under the `/api/v1` prefix. Interactive OpenAPI docs
are served at `/docs` (and ReDoc at `/redoc`) only when `DEBUG=true`.

| Group | Responsibility |
| --- | --- |
| `auth` | Register, login, refresh, forgot / reset password |
| `citizen` | Citizen profile, complaint submission, ratings |
| `complaints` | Complaints CRUD, status history, department history, correlation |
| `work_orders` | Work order lifecycle, dispatch, activities, rework, worker list |
| `field_worker` | Worker jobs: accept, check-in, start, finish, evidence upload |
| `command_center` | Operations dashboard: live metrics and supervision |
| `geo` | Ward detection, reverse geocoding, nearby places |
| `wards` | Ward reference data |
| `languages` | Supported languages / translation surface |
| `conversations` | Citizen ↔ ward office messaging threads |
| `notifications` | In-app notifications + `WS /ws/notifications` realtime socket |
| `verifications` | Repair-verification runs, verdicts, human review |
| `sla` | SLA policies and per-order SLA tracking |
| `hotspots` | Predictive hotspot forecasts (gated on real data) |
| `infrastructure` | Predictive infrastructure-risk forecasts (gated on real data) |
| `assistant` | Citizen AI assistant (RAG) |
| `classification` | ML classification service |
| `analytics` | Aggregated KPIs and trend data |
| `ratings` | Citizen ratings on resolutions |
| `admin` | Application administration |
| `governance` | Agent runs/events audit records |
| `health` | Liveness / readiness probes |

A command-center realtime socket (`WS /ws/command-center`) streams live
operations events when enabled.

## Data & Database

Schema is managed with **Alembic**; the database is PostgreSQL with **PostGIS**
(geography / ward boundaries) and **pgvector** (embeddings for duplicate
detection and the assistant RAG). See `docs/database.md` for the full data model
and local install notes. Principal domains:

- **Identity & access** — roles, users, profiles, refresh-token revocation,
  ward membership, department assignments.
- **Complaints** — the complaint itself, media (`complaint_media`), locations,
  status history, department history, priority history, ratings,
  correlation + embeddings.
- **Work orders** — lifecycle, worker lifecycle, status history, activities +
  photos, rework reasons, verifications, GPS accuracy, HITL assignment sources.
- **Governance** — agent runs / agent events, SLA policies, notifications
  (with titles / read state), conversations + messages + reads.
- **Reference & spatial** — ward boundaries, critical infrastructure locations,
  multilingual content, assistant knowledge base.
- **ML** — hotspot feature/forecast tables, infrastructure corpus + risk tables.

The platform **ships empty**: no fake complaints, hotspots, or analytics are
seeded into a fresh install. `backend/seed.py` exists only as a documented
reference for populating a development database.

## Security & Governance

- **Passwords:** hashed with **Argon2id** (OWASP-recommended parameters); plain
  text is never stored. Strong-password policy enforced at sign-up.
- **Authentication:** short-lived access JWT (30 min) + revocable refresh JWT
  (7 days), signed HS256; issuer/audience checks on every decode.
- **Rate limiting:** slowapi limiter on authentication and sensitive endpoints
  (can be disabled for test suites).
- **Security headers:** a dedicated middleware sets standard hardening headers
  on every response.
- **Secrets:** read only from environment variables; the developer-provided
  `JWT_SECRET`, `GROQ_API_KEY` etc. are never logged or shipped to the browser.
  See [`SECURITY.md`](SECURITY.md).
- **Media:** uploads are validated for type and size, and local storage serves
  files only through short-lived HMAC-signed URLs.
- **Audit:** every agent run, routing/priority decision, dispatch, and
  human override is persisted (agent runs/events, status + department history)
  for later review.
- **Human accountability:** officers approve routing overrides and settle
  verification verdicts; P1-critical closures always require authorized human
  sign-off even when the vision model is confident.

## Getting Started

### Prerequisites

- Docker + Docker Compose (easiest path), **or** a local Python ≥3.11 env,
  PostgreSQL 17 (or 16) with PostGIS + pgvector, and Redis.
- A Groq API key for the AI features (optional — without one everything runs,
  but AI triage, vision, and the assistant are unavailable). See
  [AI / LLM Setup](#ai--llm-setup).

### Option A — Docker Compose (recommended)

```bash
cp .env.example .env                      # fill in JWT_SECRET, GROQ_API_KEY
docker compose -f infrastructure/docker-compose.yml up --build
```

- Backend: <http://localhost:8000>  (API docs at `/docs` when `DEBUG=true`)
- Frontend: <http://localhost:3000>
- Profile overrides exist for local dev, testing, and MinIO/S3:
  `docker-compose.dev.yml`, `docker-compose.test.yml`,
  `docker-compose.minio.yml`. See `infrastructure/.env.docker.example` for the
  compose-specific variables.

### Option B — Local development

```bash
# 1. Database (local PostgreSQL 17 on 5433, db/user civicagent) — see docs/database.md
# 2. Backend
cd backend
python -m venv .venv && .venv/Scripts/activate   # Windows (pwsh: .venv\Scripts\Activate.ps1)
pip install -e ".[dev]"
copy .env.example .env                           # adjust DATABASE_URL / JWT_SECRET
alembic upgrade head
uvicorn main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
copy .env.local.example .env.local              # set NEXT_PUBLIC_API_URL
npm run dev                                      # -> http://localhost:3000
```

## Environment Variables

The authoritative list is in [`.env.example`](.env.example) (and the compose
reference in `infrastructure/.env.docker.example`). The most important ones:

| Variable | Purpose | Default / notes |
| --- | --- | --- |
| `JWT_SECRET` | HS256 signing secret, ≥32 bytes | **set one**, `secrets.token_urlsafe(48)` |
| `DATABASE_URL` | Async Postgres DSN | `postgresql+asyncpg://civicagent:civicagent@localhost:5433/civicagent` |
| `REDIS_URL` | Redis DSN | `redis://localhost:6379/0` |
| `GROQ_API_KEY` | Groq API key (chat + vision) | required for AI features |
| `GROQ_MODEL` / `VISION_MODEL` | Chat and vision models | `openai/gpt-oss-120b`, `qwen/qwen3.8-27b` |
| `STORAGE_BACKEND` | `local` or `s3` | `local` |
| `CORS_ORIGINS` | Allowed frontend origins | `http://localhost:3000` |
| `DEBUG` | Enable `/docs`, `true` only in dev | `false` |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL (build time) | `http://localhost:8000` |
| `EMAIL_PROVIDER` | `console` or `smtp` | `console` (no credentials) |

Runtime tuning for the agents (priorities, routing, dispatch weights, ML gating,
timeouts, cache TTLs, media limits, …) is also available through environment
variables — all documented in `config.py` and `.env.example`.

## AI / LLM Setup

1. Create an API key at <https://console.groq.com/keys> and set `GROQ_API_KEY`.
2. Verify the configured models exist on your account: the defaults
   (`GROQ_MODEL=openai/gpt-oss-120b`, `VISION_MODEL=qwen/qwen3.8-27b`) were
   checked against Groq's live model list; list your available models with
   `groq.models.list()` if you change them.
3. The embedding model (`BAAI/bge-small-en-v1.5`) is **local and offline**; it
   needs no API key. Weather (Open-Meteo) and reverse geocoding (Nominatim) are
   free public services that also need no key and degrade gracefully.
4. Predictive hotspot / infrastructure forecasts are trained **only after** the
   platform accumulates the configured minimum of real data
   (`MINIMUM_TRAINING_RECORDS`, `MINIMUM_AREA_TIME_OBSERVATIONS`,
   `INFRA_MIN_ASSETS`); below that, ML surfaces return `INSUFFICIENT_DATA`.

## Storage

- **Local (default):** uploads go to `backend/uploads/` and are served through
  signed media URLs.
- **S3 / MinIO:** set `STORAGE_BACKEND=s3`, provide `S3_*` credentials, and set
  `S3_PUBLIC_BASE_URL` to a location that allows anonymous downloads of the
  bucket path. The Compose MinIO profile (`docker-compose.minio.yml`) starts a
  local server for development.

## Testing & CI

```bash
# Backend (requires local Postgres + Redis, or rely on CI)
cd backend
ruff check . && ruff format --check .
pytest -q                                   # 496 tests (1 skipped)

# Frontend
cd frontend
npm run lint
npm run typecheck
npm test                                    # vitest (40 tests)
npm run build
```

CI runs automatically on push to `master` and on pull requests via the
workflows in `.github/workflows/` (lint, typecheck, frontend tests + build,
backend tests against a disposable PostGIS service, Docker compose + image
builds).

## Demo Workflow

The Compose dev/test profiles can seed a reference dataset with
`SEED_DEMO_DATA=true`. Development-only login accounts created by `seed.py`:

| Role | Login | Password |
| --- | --- | --- |
| Admin | `admin@example.com` | `CivicAgent#2026` |
| Field worker | `worker.1@example.com` … `worker.25@example.com` | `FieldWorker#2026` |
| Ward rep | `kobu.jadav@example.com`, `dheeraj.borse@example.com`, `rushikesh.tapsale@example.com`, `rajveer.rajput@example.com` | `1234#Rushi` |

Reference `seed.py` creates the four seeded wards (`WARD-1` … `WARD-4`),
seven departments, roles, an AI knowledge base, and the accounts above. These are
**development conveniences only** — never enable `SEED_DEMO_DATA` in production.

End-to-end walkthrough: report a water-leak complaint from the citizen portal
with a photo and GPS → watch triage, priority, and routing metadata attach on
the officer dashboard → accept the resulting work order as a field worker →
upload BEFORE/AFTER photos → officers verify the repair → the citizen rates the
resolution.

## Known Limitations

- **AI features require a Groq API key.** Without it the platform still works,
  but AI triage, vision evidence analysis, repair verification, and the citizen
  assistant are unavailable.
- **Docs & ReDoc are dev-only** (they render only when `DEBUG=true`).
- **Public API dependencies:** Nominatim and Open-Meteo are free, rate-limited
  services; clients time out, retry, and degrade gracefully, but availability is
  outside our control.
- **ML forecasts are data-gated**: hotspot and infrastructure models report
  `INSUFFICIENT_DATA` until real operational data reaches the configured
  minimums; seed data never counts toward these thresholds.
- **ETA is an estimate** unless a live routing provider is configured
  (`ROUTING_API_URL` / `ROUTING_API_KEY`); results are always labeled
  `live` / `estimated`.
- **Email notifications default to the `console` provider** — real SMTP
  requires configuration.
- **Reference ward boundaries and geographies are illustrative
  (`GIS_DEMO_LABEL = "DEMO DATA"`), not authoritative civic data.**

## Roadmap

Planned future work (not yet implemented — listed for transparency):

- Map provider integration for richer basemap / routing UX.
- Automated, scheduled retraining & drift monitoring for the ML pipelines.
- Configurable notification channels beyond in-app + email (e.g. SMS).
- Additional vision providers and multi-model consensus for evidence review.
- Hardened production hardening review: cloud secrets manager, object-lifecycle
  rules, audit-log retention policy.

## Contributing

Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) for the development workflow,
code style (ruff + ESLint), test expectations, and the PR process. All changes
are validated by CI before merge.

## License

License **not yet specified**. Please do not redistribute or use this software
commercially until a license is formally chosen. Contact the maintainers for
details.