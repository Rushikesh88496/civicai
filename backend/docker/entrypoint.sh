#!/bin/sh
# CivicAgent backend container entrypoint.
#
# Runs database migrations before the web server starts, then executes the
# container command (default: uvicorn). Migrations are idempotent (alembic), so
# restarting a healthy container is a no-op. Demo seeding is opt-in via the
# SEED_DEMO_DATA env var (dev/test only — never enabled in production).
set -e

# ---------------------------------------------------------------------------
# 1. Wait for PostgreSQL to accept connections (max ~120s, then fail loudly so
#    the orchestrator can restart the container).
# ---------------------------------------------------------------------------
if [ -n "${DATABASE_URL:-}" ]; then
  echo "[entrypoint] waiting for PostgreSQL to accept connections..."
  i=0
  until python -c "
import asyncio
import os
import sys

async def probe() -> bool:
    try:
        import asyncpg
        conn = await asyncpg.connect(os.environ[\"DATABASE_URL\"])
        await conn.close()
        return True
    except Exception:
        return False

sys.exit(0 if asyncio.run(probe()) else 1)
" 2>/dev/null || [ "$i" -ge 60 ]; do
    i=$((i + 1))
    sleep 2
  done
  echo "[entrypoint] PostgreSQL is ready."
fi

# ---------------------------------------------------------------------------
# 2. Apply schema migrations (safe: alembic, idempotent, sequential).
# ---------------------------------------------------------------------------
echo "[entrypoint] applying database migrations (alembic upgrade head)..."
alembic upgrade head

# ---------------------------------------------------------------------------
# 3. Optional demo seed (dev/test only).
# ---------------------------------------------------------------------------
if [ "${SEED_DEMO_DATA:-false}" = "true" ]; then
  echo "[entrypoint] seeding demo data (SEED_DEMO_DATA=true)..."
  python seed.py
fi

# ---------------------------------------------------------------------------
# 4. Run the container command.
# ---------------------------------------------------------------------------
echo "[entrypoint] starting: $*"
exec "$@"