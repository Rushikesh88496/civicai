# CivicAgent

**Smarter Cities. Faster Civic Response.**

CivicAgent is an autonomous civic governance platform that receives citizen complaints, analyzes them using AI, enriches them with GIS/weather/context data, prioritizes them, generates municipal work orders, coordinates field workers, and verifies resolution.

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full technical architecture.

## Tech Stack

### Frontend
- Next.js 14+ with App Router
- React 18+
- TypeScript
- Tailwind CSS
- shadcn/ui components
- Lucide React icons
- Framer Motion

### Backend
- Python 3.11+
- FastAPI
- SQLAlchemy (async)
- Alembic migrations
- Pydantic validation

### Infrastructure
- PostgreSQL 16 + PostGIS + pgvector
- Redis 7
- Docker & Docker Compose

## Quick Start

### Prerequisites
- Node.js 18+
- Python 3.11+
- Docker & Docker Compose
- Git

### Option 1: Docker (Recommended)

```bash
# Copy environment file (templates for Compose live in infrastructure/)
cp .env.example .env
cp infrastructure/.env.docker.example infrastructure/.env
# REQUIRED: set a real JWT_SECRET in infrastructure/.env (>= 32 bytes)

# Start all services (migrations + healthchecks handled automatically)
cd infrastructure
docker compose --env-file ../.env up -d --build

# Frontend: http://localhost:3000
# Backend API: http://localhost:8000
# API Docs: http://localhost:8000/docs
```

Other Compose profiles / variants:

```bash
# Development (hot reload, DEBUG on, demo seed)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Run the test suites in the containerized topology
docker compose -f docker-compose.yml -f docker-compose.test.yml run backend
docker compose -f docker-compose.yml -f docker-compose.test.yml run frontend

# Optional MinIO/S3 storage
docker compose -f docker-compose.yml -f docker-compose.minio.yml up -d --build
```

Migrations run automatically on container startup (`alembic upgrade head`, then
the demo seed when `SEED_DEMO_DATA=true`). To run them manually:

```bash
cd backend
alembic upgrade head   # apply migrations
python seed.py         # idempotent demo data (dev/test only)
```

### Option 2: Local Development

```bash
# Start infrastructure (PostgreSQL on host port 5433, Redis)
cd infrastructure
docker compose -f docker-compose.yml up -d postgres redis

# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -e ".[dev]"
alembic upgrade head
python seed.py  # optional demo data
uvicorn main:app --reload --port 8000

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | API root |
| GET | `/api/v1/health` | Health check |
| GET | `/api/v1/system/health` | System health (DB, Redis) |
| GET | `/docs` | Swagger UI |
| GET | `/redoc` | ReDoc |

## Required API Keys

| Variable | Purpose | Where to Configure |
|----------|---------|-------------------|
| `GROQ_API_KEY` | AI/LLM analysis via Groq | `.env` file or environment |
| `JWT_SECRET` | JWT authentication tokens | `.env` file or environment |

**Note:** The application will run without these keys, but AI features and authentication will be unavailable. Set them in your `.env` file.

## Project Structure

```
civicai/
├── frontend/          # Next.js frontend
│   ├── src/
│   │   ├── app/       # Pages and routes
│   │   ├── components/
│   │   │   ├── ui/    # Reusable UI components
│   │   │   └── layout/ # Layout components
│   │   └── lib/       # Utilities and API client
│   └── package.json
├── backend/           # FastAPI backend
│   ├── app/
│   │   ├── api/       # API routes
│   │   ├── core/      # Configuration, Redis
│   │   ├── db/        # Database session
│   │   ├── models/    # SQLAlchemy models
│   │   ├── schemas/   # Pydantic schemas
│   │   ├── services/  # Business logic
│   │   ├── agents/    # AI agents (future)
│   │   ├── ml/        # ML models (future)
│   │   └── utils/     # Utilities
│   ├── alembic/       # Database migrations
│   ├── tests/         # Test suite
│   └── main.py        # FastAPI entrypoint
├── infrastructure/    # Docker, database init
├── docs/              # Documentation
└── README.md
```

## Development

### Running Tests

```bash
# Backend
cd backend
pytest

# Frontend lint
cd frontend
npm run lint
```

### Linting

```bash
# Backend
cd backend
ruff check .
ruff format .

# Frontend
cd frontend
npm run lint
```

## License

Proprietary - All rights reserved.
