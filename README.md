# 🏛️ CivicAgent

**Smarter Cities. Faster Civic Response.**

CivicAgent is an **autonomous civic governance platform** that receives citizen
complaints, analyzes them with AI, enriches them with GIS/weather/context data,
prioritizes them, detects duplicates, routes them to the right municipal
department, autonomously dispatches field workers, and verifies resolution —
end to end.

![Next.js](https://img.shields.io/badge/Next.js-16-000000?logo=nextdotjs&logoColor=white)
![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=000)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-7-DC382D?logo=redis&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?logo=docker&logoColor=white)
![License](https://img.shields.io/badge/License-Proprietary-red)

---

## 👥 Who It's For

| Portal | Role | Description |
|--------|------|-------------|
| 👤 **Citizen** | Report & track | Submit complaints with photos + GPS, chat with the AI assistant, follow status live |
| 🕹️ **Officer / Command Center** | Oversight & dispatch | Live map, priority dashboard, dispatching, verification, analytics, hotspots & infrastructure forecasts |
| 🏢 **Ward Representative** | Ward oversight | Triage queue, ward analytics, citizen relationships |
| 🛠️ **Field Worker** | Execute work | Mobile-first workbench: accept → check-in → start → finish → evidence, works **offline** |
| 🛡️ **Super Admin** | Platform control | Users, roles, wards, categories, SLA, priority weights |

## ✨ Highlights

- **🗣️ AI Triage** — Groq LLM classifies complaints, extracts entities, and flags urgency.
- **🔁 Duplicate Detection** — semantic embeddings (fastembed) + distance/time/category correlation.
- **🗺️ GIS Intelligence** — PostGIS ward detection, reverse-geocoding, nearby critical infrastructure.
- **🌦️ Context Enrichment** — real-time weather (Open-Meteo) + neighbourhood complaint history.
- **🎯 Dynamic Priority Engine** — deterministic, weighted scoring → `P1` … `P4`. An LLM never decides the score.
- **🚦 Department Routing** — explainable, rule-based routing to 7 departments with confidence.
- **📋 Autonomous Dispatch** — weighted match (skill, availability, distance, workload) to the best crew.
- **📸 AI Verification** — multimodel vision checks BEFORE/AFTER photos; low confidence → human review.
- **🔮 Predictive Models** — XGBoost hotspots & infrastructure-risk forecasts (readiness-gated, no synthetic data).
- **📴 Offline-first Field Work** — actions & evidence queue locally (IndexedDB) and sync when back online.
- **🔐 Enterprise-grade** — JWT access/refresh, RBAC, Argon2id, rate limiting, audit trail, ward isolation.

## 🏗️ Architecture

```
┌─────────────────┐      ┌─────────────────┐      ┌─────────────────┐
│    Frontend     │─────▶│   Backend API   │─────▶│   PostgreSQL    │
│   (Next.js 16)  │      │    (FastAPI)    │      │  + PostGIS      │
│    :3000        │      │     :8000       │      │  + pgvector     │
└─────────────────┘      └────────┬────────┘      └─────────────────┘
                                  │
                     ┌────────────┼────────────┐
                     │            │            │
               ┌─────▼─────┐ ┌───▼───┐ ┌──────▼──────┐
               │   Redis   │ │  Groq │ │  Storage    │
               │ cache/WS  │ │  LLM  │ │ (Local/S3)  │
               └───────────┘ └───────┘ └─────────────┘
```

### 🧠 The AI Pipeline

```
Citizen Report
   │
   ▼
NLP Triage (Groq) ──▶ category / urgency / entities
   │
   ▼
Duplicate Correlation ──▶ link or flag near-duplicates
   │
   ▼
Context Enrichment ──▶ GIS ward + weather + history
   │
   ▼
Priority Engine ──▶ deterministic P1..P4 score
   │
   ▼
Department Routing ──▶ WATER / ROADS / ELECTRICAL / WASTE / …
   │
   ▼
Autonomous Dispatch ──▶ nearest best-matched crew
   │
   ▼
Field Worker Execution ──▶ offline-safe mobile workbench
   │
   ▼
AI Resolution Verification ──▶ BEFORE / AFTER vision (human-gated)
```

## 🧰 Tech Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | Next.js 16 · React 19 · TypeScript · Tailwind CSS 4 · shadcn/ui · Framer Motion · Leaflet · Recharts |
| **Backend** | Python 3.11 · FastAPI · SQLAlchemy (async) · Alembic · Pydantic v2 · Groq LLM · fastembed · XGBoost · Argon2id |
| **Data** | PostgreSQL 16 · PostGIS · pgvector · Redis 7 |
| **Infra** | Docker & Docker Compose · MinIO/S3-compatible object storage |

## 🚀 Quick Start

### Prerequisites
- Node.js 18+ · Python 3.11+ · Docker & Docker Compose · Git

### Option 1 — Docker (recommended)

```bash
cp .env.example .env
cd infrastructure
docker compose up -d --build
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Swagger UI | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |

Migrations run automatically on startup. Manual equivalent:

```bash
cd backend
alembic upgrade head
python seed.py          # reference data only (wards, departments, demo accounts)
```

### Option 2 — Local development

```bash
# 1. Infrastructure (Postgres :5433, Redis)
cd infrastructure
docker compose up -d postgres redis

# 2. Backend
cd backend
python -m venv venv
venv\Scripts\activate           # macOS/Linux: source venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python seed.py
uvicorn main:app --reload --port 8000

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## 🔑 Environment Variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `JWT_SECRET` | ✅ | JWT signing key (≥ 32 bytes) |
| `DATABASE_URL` | ✅ | Async Postgres DSN |
| `REDIS_URL` | ✅ | Redis cache / pub-sub |
| `GROQ_API_KEY` | ⚠️ | AI triage, vision, assistant |
| `NEXT_PUBLIC_API_URL` | ⚠️ | Browser-facing backend URL |
| `STORAGE_BACKEND` | ➖ | `local` (default) or `s3` |
| `EMAIL_PROVIDER` | ➖ | `console` (default) or `smtp` |

⚠️ The app runs without AI keys, but AI features degrade.

## 👤 Demo Accounts

Seeded by `backend/seed.py` (development only — change passwords in production):

| Role | Email | Password |
|------|-------|----------|
| Super Admin | `admin@example.com` | `CivicAgent#2026` |
| Field Workers ×25 | `worker.1@example.com` … `worker.25@example.com` | `FieldWorker#2026` |
| Ward Rep — Ward 1 | `kobu.jadav@example.com` | `1234#Rushi` |
| Ward Rep — Ward 2 | `dheeraj.borse@example.com` | `1234#Rushi` |
| Ward Rep — Ward 3 | `rushikesh.tapsale@example.com` | `1234#Rushi` |
| Ward Rep — Ward 4 | `rajveer.rajput@example.com` | `1234#Rushi` |

> Four reference wards (`WARD-1` … `WARD-4`) ship with the schema, so
> registration always has wards to choose from. The platform starts **empty** —
> every number you see is produced by the real pipeline, never fabricated.

## 🧪 Testing

```bash
# Backend  (36 test modules)
cd backend && pytest

# Frontend (Vitest)
cd frontend && npm test
```

Frontend quality gates: `npm run lint`, `npm run typecheck`.

## 📍 API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/system/health` | System health (DB, Redis) |
| POST | `/api/v1/auth/login` | JWT login |
| POST | `/api/v1/complaints/media` | Upload evidence |
| POST | `/api/v1/complaints` | Submit a complaint |
| GET | `/api/v1/wards` | Public ward picker |

Interactive docs: **`/docs`** (Swagger UI) and **`/redoc`**.

---

<div align="center">

**Built for citizen-centric, data-driven municipal governance.**

</div>