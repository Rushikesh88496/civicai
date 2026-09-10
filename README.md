# CivicAgent

**Smarter Cities. Faster Civic Response.**

CivicAgent is an autonomous civic governance platform that receives citizen
complaints, analyzes them with AI, enriches them with GIS/weather/context data,
prioritizes them, detects duplicates, routes them to municipal departments,
generates work orders, autonomously dispatches field workers, and verifies
resolution against photo evidence.

The platform ships **genuinely empty** — zero complaints, hotspots, predictions
or analytics. A reference-only seed installs municipal reference data (wards,
departments, demo critical-infrastructure placeholders, an AI knowledge base, a
bootstrap super-admin, 25 field workers and 4 ward representatives) so every
number you see is produced by the pipeline from real operational data, never
invented.

## Table of Contents

- [Portals & Roles](#portals--roles)
- [Key Features](#key-features)
- [AI Pipeline](#ai-pipeline)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Structure](#repository-structure)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Demo Accounts](#demo-accounts)
- [Running Tests](#running-tests)
- [API](#api)
- [Documentation](#documentation)
- [License](#license)

## Portals & Roles

| Portal | Role | Path |
|--------|------|------|
| Citizen | Submit & track complaints, AI assistant | `/` |
| Officer / Command Center | Review complaints, dispatch, verify, dashboards, hotspots, infrastructure | `/officer` |
| Ward Representative | Triage, ward analytics & oversight | `/ward-rep` |
| Field Worker | Mobile-first order workbench (accept, check-in, startwork, finish, evidence, offline sync) | `/worker` |
| Super Admin | System management panel | admin login |

## Key Features

### Citizen Experience
- 5-step **Report Wizard**: describe → evidence → location (GPS/manual) → review → submit.
- Media upload with progress, MIME allowlist + magic-byte validation, and per-type size limits.
- Complaint tracking with live status timeline and public tracking.
- **Citizen AI Assistant** (RAG): answers from the municipal policy knowledge base with an anti-hallucination disclaimer.
- Real-time notification center with in-app storage and WebSocket push (polling fallback).

### Intelligence Layer
- **AI Triage Agent** (Groq LLM): category, urgency, key-entity extraction.
- **Duplicate / Incident Correlation**: offline `fastembed` (BGE-small) semantic similarity + distance/time/category, auto-flags `POSSIBLE_DUPLICATE`.
- **GIS Service**: PostGIS reverse-geocoding, ward detection from coordinates (Nominatim, no API key), nearby critical-infrastructure lookup.
- **Context Enrichment**: weather from Open-Meteo (cached), historical complaint history for the area.
- **Dynamic Priority & Risk Engine**: deterministic weighted scoring (severity, weather, location, crowd, history, time) → `P1..P4` buckets. An LLM never decides the score.
- **Department Routing Agent**: deterministic rule-based routing to 7 departments (WATER, ROADS, ELECTRICAL, WASTE, DRAINAGE, PARKS, EMERGENCY_DISASTER) with explainable confidence and optional secondary departments.

### Autonomous Dispatch & Field Operations
- **Work Order generation & autonomous dispatch**: weighted scoring (availability, skill, distance, workload, equipment, department, ward, priority) with ETA estimation (live provider or labelled estimate).
- **Field Worker mobile workbench**: 6-step workflow (accept → check-in → start work → finish → evidence → officer verification), gradient status UI.
- **Offline queue**: evidence and actions persist locally (IndexedDB) and sync when back online — every state transition is honest even offline.

### Verification & Governance
- **Vision evidence verification** (Groq multimodal): validates evidence photos against the complaint.
- **AI Resolution Verification**: compares BEFORE/AFTER photos, confidence-gated, forced `NEEDS_HUMAN_REVIEW` below the floor; P1/CRITICAL always requires human sign-off.
- **Human-in-the-loop** assignment and officer override for routing (defense-in-depth off switch).
- **Audit trail**, **RBAC** (6 roles), **ward isolation**, **SLA monitor**, rate limiting (slowapi), JWT access/refresh tokens.

### Predictive ML (readiness-gated)
- **Predictive Civic Hotspots**: XGBoost classifier/regressor trained on real complaint history with expanding-window CV, external-feature dropout, and a grid of the city.
- **Predictive Infrastructure Maintenance**: asset failure-risk forecasts (`LOW/MEDIUM/HIGH/CRITICAL`).
- Models only train/serve once the platform holds a minimum amount of real data; otherwise every ML surface reports `INSUFFICIENT_DATA` — no synthetic forecasts.

### Media & Storage
- Pluggable `Storage` abstraction: `local` (default) or S3/MinIO (`STORAGE_BACKEND=s3`).
- Signed, expiring media URLs (HMAC) — browsers cannot send `Authorization`, so `/<path>` media is token-protected; binaries never live in Postgres.

## AI Pipeline

```
Citizen Report
   │
   ▼
NLP Triage (Groq) ──▶ Category / Urgency / Entities
   │
   ▼
Duplicate Correlation (embeddings + Geo/Time) ──▶ link / flag duplicates
   │
   ▼
Context Enrichment (GIS ward + weather + history)              ┌────────────┐
   │                                                          │  RLHF-ish  │
   ▼                                                          │ guardrails │
Priority / Risk Engine (deterministic weights) ──▶ P1..P4     └────────────┘
   │
   ▼
Department Routing Agent ──▶ WATER / ROADS / ELECTRICAL / ...
   │
   ▼
Work Order Generation + Autonomous Dispatch ──▶ nearest skilled crew
   │
   ▼
Field Worker Execution (offline-safe mobile workbench)
   │
   ▼
AI Resolution Verification (BEFORE/AFTER vision, human-gated)
```

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   Backend API   │────▶│   PostgreSQL    │
│   (Next.js)     │     │   (FastAPI)     │     │  + PostGIS      │
│   Port: 3000    │     │   Port: 8000    │     │  + pgvector     │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌───▼───┐ ┌──────▼──────┐
              │   Redis   │ │  Groq │ │  Storage    │
              │  cache/WS │ │  LLM  │ │ (Local/S3)  │
              └───────────┘ └───────┘ └─────────────┘
```

Monorepo with a decoupled Next.js frontend and FastAPI backend:

- **Backend** — layered: API routers → Pydantic schemas → service layer → SQLAlchemy ORM; plus `app/agents` (triage, correlation, context, priority-history guards, routing, assistant, vision/verification) and `app/ml` (hotspot + infrastructure forecasting).
- **Frontend** — App Router, Server Components by default with client islands for interactivity; shadcn/ui-style components, Tailwind, Lucide icons, Framer Motion, Leaflet maps, Recharts dashboards.
- **Infrastructure** — Docker Compose topology matching production (frontend + backend + Postgres + Redis), optional MinIO, `init.sql` enabling PostGIS & pgvector.

## Tech Stack

### Frontend
- Next.js 16 (App Router) + React 19, TypeScript
- Tailwind CSS 4, shadcn/ui patterns, Lucide React, Framer Motion
- Leaflet (maps), Recharts (analytics), Vitest + Testing Library

### Backend
- Python 3.11+ · FastAPI · SQLAlchemy (async) · Alembic · Pydantic v2
- Groq LLM (chat + multimodal vision) · fastembed (BGE-small) · XGBoost
- Argon2id passwords · slowapi rate limiting · boto3 (S3/MinIO) · Pillow

### Infrastructure
- PostgreSQL 16 + PostGIS + pgvector · Redis 7 · Docker & Docker Compose

## Repository Structure

```
civicai/
├── frontend/               # Next.js frontend
│   ├── src/
│   │   ├── app/            # Routes: citizen (/), officer, ward-rep, worker, admin
│   │   ├── components/     # ui/, layout/, report/, field-worker/, officer/…
│   │   └── lib/            # API client, auth, Leaflet init, offline queue
│   └── package.json
├── backend/                # FastAPI backend
│   ├── app/
│   │   ├── api/            # Routers (auth, complaints, work-orders, admin…)
│   │   ├── agents/         # Triage, correlation, context, routing, assistant, vision
│   │   ├── ml/             # Hotspots + infrastructure forecasting (XGBoost)
│   │   ├── models/         # SQLAlchemy models
│   │   ├── schemas/        # Pydantic schemas
│   │   ├── services/       # Business logic (dispatch, verification, priority…)
│   │   ├── storage/        # Local / S3 storage abstraction
│   │   ├── core/           # Settings, security, Redis
│   │   ├── db/             # Session
│   │   └── utils/
│   ├── alembic/            # Migrations (incl. reference wards 31a2b3c4d5e6)
│   ├── scripts/            # e2e helpers, reset_dev_data
│   ├── tests/              # Backend test suite
│   ├── seed.py             # Reference-only seed (idempotent)
│   └── main.py             # FastAPI entrypoint
├── infrastructure/         # Docker Compose (dev/test/minio/postgres), init.sql, env templates
├── docs/                   # architecture.md, database.md, development.md
└── README.md
```

## Quick Start

### Prerequisites
- Node.js 18+ · Python 3.11+ · Docker & Docker Compose · Git

### Option 1: Docker (Recommended)

```bash
# Copy environment templates
cp .env.example .env
cp infrastructure/.env.docker.example infrastructure/.env
# REQUIRED: set a real JWT_SECRET (>= 32 bytes) in infrastructure/.env

# Start all services (migrations + reference seed handled automatically)
cd infrastructure
docker compose --env-file ../.env up -d --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

Other Compose profiles:

```bash
# Development (hot reload, DEBUG on, demo seed)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Test suites in the containerized topology
docker compose -f docker-compose.yml -f docker-compose.test.yml run backend
docker compose -f docker-compose.yml -f docker-compose.test.yml run frontend

# Optional MinIO/S3 object storage
docker compose -f docker-compose.yml -f docker-compose.minio.yml up -d --build
```

Migrations run automatically on container startup (`alembic upgrade head`, then
the reference seed when `SEED_DEMO_DATA=true`). To run them manually:

```bash
cd backend
alembic upgrade head      # apply migrations
python seed.py            # reference data only (dev/test)
```

### Option 2: Local Development

```bash
# Start infrastructure (Postgres on host port 5433, Redis)
cd infrastructure
docker compose -f docker-compose.yml up -d postgres redis

# Backend
cd backend
python -m venv venv
venv\Scripts\activate          # or: source venv/bin/activate (macOS/Linux)
pip install -e ".[dev]"
alembic upgrade head
python seed.py                 # optional reference data
uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## Environment Variables

See `.env.example`. All variables are documented in `backend/app/core/config.py`.

| Variable | Required | Purpose |
|----------|----------|---------|
| `JWT_SECRET` | Yes | JWT signing key, must be ≥ 32 bytes (HS256) |
| `DATABASE_URL` | Yes | Async Postgres DSN (`postgresql+asyncpg://…`) |
| `REDIS_URL` | Yes | Redis cache / pub-sub URL |
| `GROQ_API_KEY` | No* | AI triage, vision verification, assistant (Groq) |
| `NEXT_PUBLIC_API_URL` | No* | Browser-visible backend URL for the frontend |
| `STORAGE_BACKEND` | No | `local` (default) or `s3` (MinIO/S3) |
| `S3_*` | No | Endpoint/keys/region when `STORAGE_BACKEND=s3` |
| `EMAIL_PROVIDER` | No | `console` (default, no creds) or `smtp` |
| `SEED_DEMO_DATA` | No | Docker only: run reference seed on boot |

\* The app runs without these keys, but AI features / auth (and remote API URLs)
would be unavailable. Get a Groq key at [console.groq.com](https://console.groq.com).

## Demo Accounts

Seeded by `backend/seed.py` (dev/test only — change passwords in production):

| Role | Email | Password |
|------|-------|----------|
| Super Admin | `admin@example.com` | `CivicAgent#2026` |
| Field Workers (25) | `worker.1@example.com` … `worker.25@example.com` | `FieldWorker#2026` |
| Ward Rep — Ward 1 | `kobu.jadav@example.com` | `1234#Rushi` |
| Ward Rep — Ward 2 | `dheeraj.borse@example.com` | `1234#Rushi` |
| Ward Rep — Ward 3 | `rushikesh.tapsale@example.com` | `1234#Rushi` |
| Ward Rep — Ward 4 | `rajveer.rajput@example.com` | `1234#Rushi` |

- Four reference wards (`WARD-1` .. `WARD-4`) and their boundary polygons arrive
  via the `31a2b3c4d5e6` migration, so fresh deploys always have sign-up wards.
  Registration **requires** selecting a ward.
- New citizens register through the sign-up page — there is no seeded citizen.

## Running Tests

```bash
# Backend (36 test modules)
cd backend
pytest

# Frontend (Vitest suite)
cd frontend
npm test          # vitest run

# Lint / type checks
cd frontend
npm run lint
npm run typecheck
cd ../backend
ruff check .
```

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API root |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/system/health` | System health (DB, Redis) |
| POST | `/api/v1/auth/login` | JWT login (access + refresh) |
| POST | `/api/v1/complaints/media` | Upload evidence (image/video) |
| POST | `/api/v1/complaints` | Submit a complaint (CITIZEN) |
| GET | `/api/v1/wards` | Public ward picker |
| … | `/api/v1/work-orders` | Dispatch & field operations |

Full, interactive documentation is available at `/docs` (Swagger UI) and
`/redoc` when the backend is running. Only the primary citizens → orders flow is
listed above; the platform exposes many additional routers (events, notifications,
analytics, hotspots, infrastructure, admin, governance, assistant, …).

## Documentation

- [Architecture](docs/architecture.md)
- [Database](docs/database.md)
- [Development guide](docs/development.md)

## License

Proprietary — all rights reserved.