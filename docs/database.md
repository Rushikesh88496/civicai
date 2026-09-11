# CivicAgent — PostgreSQL Database Setup

This document explains the PostgreSQL database configuration for CivicAgent.

## Overview

CivicAgent uses **PostgreSQL** as its primary relational database, extended with
**PostGIS** (geospatial) and **pgvector** (vector / embeddings). The backend connects
asynchronously via **SQLAlchemy + asyncpg**, and schema changes are managed with
**Alembic** migrations.

## PostgreSQL Installation

- **Server:** local PostgreSQL 17 running as a Windows service
  (`postgresql-x64-17`, data dir `C:\Program Files\PostgreSQL\17\data`)
- **Version:** PostgreSQL 17.11
- **Port:** `5433` (see `postgresql.conf` → `port = 5433`)
- **psql:** `C:\Program Files\PostgreSQL\17\bin\psql.exe`
  (not on `PATH` by default — add the `bin` dir to `PATH`, or use the full path)

> Note: A second, older PostgreSQL 18 instance also exists on this machine
> (`postgresql-x64-18`, port 5432) but is **stopped** and **not used**. The active
> database for CivicAgent is PostgreSQL **17 on port 5433**.

### Starting / status

```powershell
# Check service status
Get-Service postgresql-x64-17

# Start the service (requires an Administrator PowerShell/terminal)
Start-Service postgresql-x64-17

# Stop
Stop-Service postgresql-x64-17
```

### Connecting with psql

```powershell
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h localhost -p 5433 -U civicagent -d civicagent
```

## Database Objects

| Object | Value |
|--------|-------|
| Database | `civicagent` |
| Database user (role) | `civicagent` (owner of the `civicagent` database) |
| Host | `localhost` |
| Port | `5433` |
| Auth | `scram-sha-256` (password) |

## DATABASE_URL

The backend reads the database connection from the `DATABASE_URL` environment variable
(defined in the project `.env`). Format:

```
postgresql+asyncpg://USER:PASSWORD@HOST:PORT/DATABASE
```

Explained in simple terms:

- `postgresql+asyncpg://` — the SQLAlchemy async driver scheme. `asyncpg` is used for
  fast, asynchronous (non-blocking) PostgreSQL access.
- `USER` — the database role, e.g. `civicagent`.
- `PASSWORD` — that role's password.
- `HOST` — the server host, e.g. `localhost`.
- `PORT` — the listening port, e.g. `5433`.
- `DATABASE` — the database name, e.g. `civicagent`.

Example (password is a placeholder — replace it):

```
DATABASE_URL=postgresql+asyncpg://civicagent:YOUR_CIVICAGENT_PASSWORD@localhost:5433/civicagent
```

> **Passwords with special characters** such as `@`, `:`, `/`, `#`, `%`, `?`, `&` must be
> URL-encoded in the connection string (e.g. `@` → `%40`, `:` → `%3A`, `#` → `%23`).
>
> e.g. a password of `1234#Rushi` becomes `1234%23Rushi`.

## Environment Variables

Create a `.env` file in the `backend/` directory and optionally at the repo root
(copy from `.env.example`). Never commit `.env` to version control — it is
gitignored.

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | Full async connection string |
| `REDIS_URL` | Redis connection (separate infra) |
| `JWT_SECRET` | JWT signing secret (set a strong value for production) |
| `GROQ_API_KEY` | Groq LLM API key (used by future AI features) |
| `GROQ_MODEL` | Groq model name to use |
| `STORAGE_BACKEND` | Storage backend: `local` (default) or `s3` / `minio` (S3-compatible) |
| `STORAGE_LOCAL_DIR` | Local directory used when `STORAGE_BACKEND=local` (default `uploads`) |
| `MAX_IMAGE_MB` | Max allowed size per image upload (default `10`) |
| `MAX_VIDEO_MB` | Max allowed size per video upload (default `50`) |
| `ALLOWED_IMAGE_TYPES` | Comma-separated image MIME allowlist |
| `ALLOWED_VIDEO_TYPES` | Comma-separated video MIME allowlist |
| `S3_ENDPOINT_URL` | S3/MinIO endpoint when `STORAGE_BACKEND=s3` |
| `S3_ACCESS_KEY` | S3/MinIO access key |
| `S3_SECRET_KEY` | S3/MinIO secret key |
| `S3_BUCKET` | S3 bucket name |
| `S3_REGION` | S3 region (e.g. `us-east-1`) |
| `S3_SECURE` | Use HTTPS for S3 (`true`/`false`) |
| `S3_PUBLIC_BASE_URL` | Public URL prefix for serving S3 media (optional) |
| `CORS_ORIGINS` | Allowed browser origins |
| `DEBUG` | Enable DB query echoing during development |

## Installing PostGIS and pgvector (REQUIRED for migrations)

The initial migration enables the `postgis` and `vector` extensions. These are **not**
bundled with a default PostgreSQL Windows install, so the migration will fail with
"extension postgis is not available / could not open extension control file .../17/share/extension/postgis.control"
until the extension binaries are installed system-wide. Install them first:

### PostGIS

PostGIS for Windows is provided via the **Stack Builder** (shipped with the EnterpriseDB
installer) or via the PostGIS bundle on the official web site:

1. Run **Stack Builder** (`C:\Program Files\PostgreSQL\17\bin\StackBuilder.exe`) as
   Administrator. If not present, download the PostGIS bundle from
   https://download.osgeo.org/postgis/windows/ (pick the build matching PostgreSQL 17
   and Windows, e.g. `postgis-bundle-pg17x64 ...`).
2. Select the PostgreSQL 17 installation, then **Spatial Extensions → PostGIS x.y**.
   Follow the installer (choose the `civicagent` database pre-created by the wizard, or
   skip and enable the extension manually).
3. After install, the control files land in `C:\Program Files\PostgreSQL\17\share\extension\`
   (`postgis.control`) and library files in `C:\Program Files\PostgreSQL\17\lib\`.
   Restart the `postgresql-x64-17` service (requires Administrator).

### pgvector

There is no official one-click Windows installer for pgvector. Options:

- Prefer: build `pgvector` for the running PostgreSQL 17 using its source
  (https://github.com/pgvector/pgvector) with a Visual Studio toolchain, then copy the
  resulting `vector.dll`/`vector.control`/`vector--*.sql` files into
  `C:\Program Files\PostgreSQL\17\lib\` and `C:\Program Files\PostgreSQL\17\share\extension\`.
- Or use the release artifacts from the pgvector repo/community (pgvector for Windows)
  that match PostgreSQL 17 (e.g. prebuilt `vector--0.x.x-windows` bundles), installing the
  same three file types as above.

After copying files, restart the `postgresql-x64-17` service (Administrator).

### Verify installs (with psql as `postgres` or `civicagent`)

```sql
-- Should now show a row if installed
SELECT name, default_version FROM pg_available_extensions WHERE name IN ('postgis', 'vector');
```

Once the extension files are present, the Alembic migration will succeed:

```bash
cd backend
.venv\Scripts\alembic upgrade head
```

Until PostGIS and pgvector are installed, **DO NOT** run `alembic upgrade head` — it will
fail on `CREATE EXTENSION`. The database connection itself already works.

## Running Migrations (Alembic)

Migrations are managed with Alembic. They run asynchronously (see `backend/alembic/env.py`).

```bash
cd backend

# Create a new migration from model changes
alembic revision --autogenerate -m "describe change"

# Apply all pending migrations
alembic upgrade head

# Show current state
alembic current

# Show history
alembic history
```

The initial migration (`cfbd4ce21b49_enable_postgis_and_pgvector_extensions.py`)
enables the `postgis` and `vector` extensions.

## Verifying PostGIS

PostGIS provides geospatial types (`geometry`, `geography`) and spatial functions.

```sql
-- Is the extension enabled in the current database?
SELECT extname, extversion FROM pg_extension WHERE extname = 'postgis';

-- PostGIS version
SELECT postgis_version();
```

The backend geospatial layer uses the `GeoAlchemy2` Python package.

## Verifying pgvector

pgvector provides the `vector` type used for AI embeddings and similarity search.

```sql
-- Is the extension enabled?
SELECT extname FROM pg_extension WHERE extname = 'vector';

-- Is the vector type available?
SELECT to_regtype('vector');
```

Test that a vector column works:

```sql
CREATE TEMP TABLE t (v vector(3));
INSERT INTO t VALUES ('[1,2,3]');
SELECT v FROM t;
```

The `pgvector` Python package provides the SQLAlchemy `Vector` type.

## Connection Test API

The backend verifies database connectivity via the health endpoint which executes
`SELECT 1` internally. See `app/services/health_service.py`.

- `GET /api/v1/health` — application health
- `GET /api/v1/system/health` — includes `database` (status), `postgis`, `pgvector`,
  and `redis` status plus non-sensitive connection metadata (host/port/database only;
  never the username or password)

## Verification Script

A standalone script performs a full, non-destructive connectivity check:

```bash
cd backend
.venv\Scripts\python verify_db.py
```

It prints `PASS`/`FAIL` for:

1. PostgreSQL TCP connectivity
2. `civicagent` database existence
3. `SELECT 1`
4. PostgreSQL version
5. PostGIS enabled
6. pgvector enabled
7. pgvector `vector` type usable
8. SQLAlchemy async engine connection
9. Alembic configuration

It never prints the database password.

## Troubleshooting

**Service won't start / Access denied**

Start an Administrator PowerShell and run `Start-Service postgresql-x64-17`. The
PostgreSQL service cannot be started from a non-elevated shell.

**`psql` not recognized**

`psql.exe` is at `C:\Program Files\PostgreSQL\17\bin\psql.exe` but may not be on
`PATH`. Add `C:\Program Files\PostgreSQL\17\bin` to your user/system `PATH`, or use
the full path.

**Authentication failed for role "civicagent"**

The `civicagent` role must be created (see below). Ensure the password in `DATABASE_URL`
matches the role's password and is URL-encoded if it contains special characters.

**Alembic config error "invalid interpolation syntax ... %"**

The connection string contains a URL-encoded `%` (e.g. `%23` for a `#` password). This is
handled in `backend/alembic/env.py` (it stores the runtime URL in `config.attributes` and
escapes `%` in the ini value). If you see this error, ensure you are using the current
`env.py`.

**Connection refused**

Confirm the service is running and nothing else is bound to port 5433.

**Migration fails: extension "postgis"/"vector" is not available**

PostGIS/pgvector are not installed on the PostgreSQL 17 instance. Install them (see the
"Installing PostGIS and pgvector" section above), then re-run `alembic upgrade head`.
The core DB connection is unaffected.

**Untrusted local admin (pg_hba.conf uses scram-sha-256)**

Local connections require a password. Provide the `postgres` superuser password in a
trusted admin context to create roles/databases; never commit credentials.

## Creating the CivicAgent role and database (if not present)

This is done once during initial setup using the `postgres` superuser. Adapted for
Windows:

```powershell
$ENV:PGPASSWORD = "<postgres-superuser-password>"
& "C:\Program Files\PostgreSQL\17\bin\psql.exe" -h localhost -p 5433 -U postgres -d postgres -v ON_ERROR_STOP=1 `
  -c "CREATE ROLE civicagent WITH LOGIN PASSWORD '<civicagent-password>';" `
  -c "CREATE DATABASE civicagent OWNER civicagent;"
$ENV:PGPASSWORD = $null
```

> The commands above are informational. During automated setup the assistant creates the
> role/database for you once the `postgres` superuser password is provided. The
> `civicagent` password lives only in `.env` and is never committed.