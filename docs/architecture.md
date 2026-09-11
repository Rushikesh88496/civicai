# CivicAgent Architecture

## Overview

CivicAgent is built as a monorepo with a decoupled frontend/backend architecture. The system is designed to handle the complete lifecycle of citizen complaints through AI-powered analysis, prioritization, and resolution.

## System Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│   Backend API   │────▶│   PostgreSQL    │
│   (Next.js)     │     │   (FastAPI)     │     │   + PostGIS     │
│   Port: 3000    │     │   Port: 8000    │     │   + pgvector    │
└─────────────────┘     └────────┬────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    │            │            │
              ┌─────▼─────┐ ┌───▼───┐ ┌──────▼──────┐
              │   Redis   │ │  Groq │ │  Storage    │
              │  Cache    │ │  LLM  │ │  (S3/Local) │
              └───────────┘ └───────┘ └─────────────┘
```

## Backend Architecture

### FastAPI Application

The backend follows a layered architecture:

- **API Layer** (`app/api/`): FastAPI routers defining HTTP endpoints
- **Schema Layer** (`app/schemas/`): Pydantic models for request/response validation
- **Service Layer** (`app/services/`): Business logic and external service integration
- **Model Layer** (`app/models/`): SQLAlchemy ORM models
- **Core Layer** (`app/core/`): Configuration, Redis, shared utilities
- **Agent Layer** (`app/agents/`): AI agent orchestration (future)
- **ML Layer** (`app/ml/`): Machine learning models (future)

### Database

- **PostgreSQL**: Primary relational database
- **PostGIS**: Geospatial data and queries (complaint locations stored as `POINT` SRID 4326)
- **pgvector**: Vector similarity search for embeddings
- **Alembic**: Schema migration management

#### Complaint tables

- **`complaints`**: Core complaint record — `description`, `category`, `status`, `severity`, assigned
  agency/worker, and resolution fields.
- **`complaint_media`**: Image/video evidence attached to a complaint. Stores only metadata
  (`media_type`, `original_filename`, `content_type`, `size_bytes`) plus a `storage_key` and
  `storage_backend` reference — **binary payloads are never stored in Postgres**.
- **`complaint_locations`**: One row per complaint (unique FK) with `latitude`, `longitude`, a
  PostGIS `geom` geometry point (SRID 4326), `address`, and provenance (`source` = `gps`|`manual`,
  `geopoint_denied`).

### Media Storage

Media is stored through a pluggable abstraction (`app/storage/`) rather than directly in Postgres:

- `Storage` ABC (`base.py`) defines `save`, `delete`, and `public_url`.
- `LocalStorage` (`local.py`, default) writes files into `STORAGE_LOCAL_DIR` and serves them via the
  FastAPI `/media` static mount. Path-traversal is guarded.
- `S3Storage` (`s3.py`) implements the same interface via `boto3` for **S3 / MinIO** (S3-compatible),
  addressable by switching `STORAGE_BACKEND=s3`.

Uploads are validated server-side by MIME allowlist, magic-byte signature checks, Pillow image
verification, max dimension, and per-type size limits (`MAX_IMAGE_MB`, `MAX_VIDEO_MB`). See
`app/services/complaint_service.py`.

### Complaint Submission API

- `POST /api/v1/complaints/media` — upload a single image/video, returns a media record (`201`).
- `POST /api/v1/complaints` — create a complaint from a description, category, optional `media_ids`,
  and optional geolocation (`201`). Both require the `CITIZEN` role.

## Frontend Architecture

### Redis

- Caching layer for API responses
- Session storage
- Background task queues
- Real-time pub/sub for WebSocket events

## Frontend Architecture

### Next.js App Router

- **App Router**: File-based routing with layouts
- **Server Components**: Default for performance
- **Client Components**: For interactivity (`"use client"`)

### Component System

- **UI Components** (`src/components/ui/`): Reusable, accessible components following shadcn/ui patterns
- **Layout Components** (`src/components/layout/`): Navbar, Footer
- **Report Components** (`src/components/report/`): `MediaUploader` (image/video upload with progress),
  `LocationPicker` (GPS + manual), `ReportWizard` (5-step describe → evidence → location → review → submit)
- **Page Components** (`src/app/`): Route-specific pages

### Design System

Consistent design tokens:
- Colors: Blue-600 primary, Gray scale neutral
- Border radius: Rounded-lg (0.5rem)
- Shadows: Tailwind defaults
- Typography: Inter font family
- Spacing: Tailwind spacing scale

## AI Architecture (Future)

### Complaint Processing Pipeline

```
Citizen Report → NLP Analysis → Entity Extraction → Context Enrichment
     → Priority Scoring → Work Order Generation → Field Dispatch → Resolution Verification
```

### Components

1. **NLP Agent**: Groq LLM-powered analysis
   - Complaint classification
   - Urgency assessment
   - Entity extraction (location, issue type, severity)

2. **GIS Service**: PostGIS-powered
   - Geocoding and reverse geocoding
   - Nearby infrastructure lookup
   - Spatial clustering

3. **Weather Service**: External API integration
   - Current conditions at report location
   - Historical weather correlation

4. **Priority Engine**: ML-based scoring
   - Severity assessment
   - Population impact estimation
   - Resource availability matching

5. **Dispatch Agent**: Automated routing
   - Field worker assignment
   - Route optimization
   - SLA tracking

6. **Verification Agent**: Resolution validation
   - Photo evidence analysis
   - Follow-up citizen notification
   - Quality scoring

## Security

- JWT-based authentication (access + refresh tokens)
- Role-based access control (e.g. `CITIZEN` for complaints)
- CORS configuration
- Server-side upload validation (type allowlist, magic bytes, size limits)
- Path-traversal guard on local media storage
- Environment variable management, no hardcoded secrets

## Scalability

- Async Python for concurrent request handling
- Connection pooling (SQLAlchemy)
- Redis caching for hot data
- Horizontal scaling via Docker
