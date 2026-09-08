# Development Guide

## Prerequisites

- **Node.js** 18+ (recommended: 20 LTS)
- **Python** 3.11+
- **Docker** & **Docker Compose**
- **Git**

## Environment Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd civicai
```

### 2. Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your specific values. See `.env.example` for all available options.

### 3. Required API Keys

| Key | Variable | Purpose | How to Get |
|-----|----------|---------|------------|
| Groq API Key | `GROQ_API_KEY` | AI analysis via LLM | [console.groq.com](https://console.groq.com) |

### 4. Start Services

```bash
cd infrastructure
docker-compose up -d
```

### 5. Run Migrations

```bash
cd backend
alembic upgrade head
```

### 6. Start Development Servers

**Backend:**
```bash
cd backend
uvicorn main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm run dev
```

## URLs

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| Backend API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |
| ReDoc | http://localhost:8000/redoc |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |

## Development Commands

### Backend

```bash
# Install dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests with coverage
pytest --cov=app --cov-report=term-missing

# Lint
ruff check .

# Format
ruff format .

# Type check (if using mypy)
mypy app/
```

### Frontend

```bash
# Install dependencies
npm install

# Development
npm run dev

# Build
npm run build

# Lint
npm run lint

# Type check
npx tsc --noEmit
```

## Database

### PostgreSQL with PostGIS

The database uses PostgreSQL 16 with PostGIS and pgvector extensions. The `init.sql` script in `infrastructure/` automatically enables these extensions when the Docker container starts.

### Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Architecture Decisions

1. **Async SQLAlchemy**: Non-blocking database operations for better concurrent request handling
2. **Pydantic v2**: Strict validation with performance optimizations
3. **shadcn/ui Pattern**: Copy-paste components for full control over styling
4. **App Router**: File-based routing with layouts for better code organization
5. **Docker Compose**: Full local development environment matching production topology

## Code Style

### Python
- Follow PEP 8
- Use type hints
- Max line length: 100 characters
- Use ruff for linting and formatting

### TypeScript
- Use strict TypeScript
- Prefer `const` over `let`
- Use Tailwind utility classes
- Components: PascalCase, files: kebab-case
