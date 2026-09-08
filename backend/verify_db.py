"""CivicAgent database verification script.

Usage:
    python verify_db.py

Checks (non-destructive, no secrets printed):
    1. PostgreSQL TCP connectivity (host:port)
    2. civicagent database exists
    3. SELECT 1
    4. PostgreSQL version
    5. PostGIS extension available/enabled
    6. pgvector extension available/enabled
    7. SQLAlchemy async engine connection
    8. Alembic configuration loads

Exit code 0 if all PASS, 1 if any FAIL.
"""

import asyncio
import os
import sys


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    candidates = [os.path.join("app", ".env"), ".env", "../.env", "backend/.env"]
    for path in candidates:
        if os.path.isfile(path):
            for line in open(path, encoding="utf-8"):
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip().strip('"').strip("'")
            break
    for key, value in os.environ.items():
        env[key] = value
    return env


def url_meta(database_url: str) -> dict[str, str | int]:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(database_url)
    return {
        "host": parsed.hostname or "",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/") or "",
        "user": parsed.username or "",
        "password": unquote(parsed.password or ""),
    }


def is_port_open(host: str, port: int) -> bool:
    try:
        import socket

        with socket.create_connection((host, port), timeout=5):
            return True
    except Exception:
        return False


def get_database_url(env: dict[str, str]) -> str:
    return env.get("DATABASE_URL", "")


async def check(env: dict[str, str]) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    database_url = get_database_url(env)

    if not database_url:
        results.append(("DATABASE_URL", False, "not set in env/.env"))
        return results

    meta = url_meta(database_url)
    host = str(meta["host"])
    port = int(meta["port"])

    tcp_ok = is_port_open(host, port)
    results.append(
        (f"PostgreSQL TCP ({host}:{port})", tcp_ok, "reachable" if tcp_ok else "unreachable")
    )
    if not tcp_ok:
        return results

    try:
        import asyncpg

        conn = await asyncpg.connect(
            host=host,
            port=port,
            user=str(meta["user"]),
            password=str(meta["password"]),
            database=str(meta["database"]) or "postgres",
            timeout=5,
        )
        results.append(("AsyncPG import", True, asyncpg.__version__))

        db_name = str(meta["database"])
        db_exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db_name)
        results.append(
            (f"Database '{db_name}' exists", bool(db_exists), "yes" if db_exists else "no")
        )

        select_one = await conn.fetchval("SELECT 1")
        results.append(("SELECT 1", select_one == 1, str(select_one)))

        version = await conn.fetchval("SELECT version()")
        results.append(("PostgreSQL version", bool(version), str(version).split(",")[0]))

        postgis_ok = await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'postgis'")
        results.append(("PostGIS enabled", bool(postgis_ok), "yes" if postgis_ok else "no"))
        if postgis_ok:
            pgver = await conn.fetchval("SELECT postgis_version()")
            results.append(("PostGIS check", bool(pgver), str(pgver)))

        pgvector_ok = await conn.fetchval("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        results.append(("pgvector enabled", bool(pgvector_ok), "yes" if pgvector_ok else "no"))
        if pgvector_ok:
            try:
                async with conn.transaction():
                    await conn.execute("CREATE TEMP TABLE __vtest (v vector(3)) ON COMMIT DROP")
                    await conn.execute("INSERT INTO __vtest VALUES ('[1,2,3]')")
                    vec = await conn.fetchval("SELECT v FROM __vtest LIMIT 1")
                results.append(("pgvector vector type", bool(vec), "usable"))
            except Exception as exc:  # noqa: BLE001
                results.append(("pgvector vector type", False, str(exc)))
        await conn.close()
    except Exception as exc:  # noqa: BLE001
        results.append(("AsyncPG connection", False, str(exc)))

    try:
        from sqlalchemy.ext.asyncio import create_async_engine

        engine = create_async_engine(database_url, pool_pre_ping=True)
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))
        await engine.dispose()
        results.append(("SQLAlchemy async engine", True, "connected"))
    except Exception as exc:  # noqa: BLE001
        results.append(("SQLAlchemy async engine", False, str(exc)))

    try:
        import alembic.config

        cfg = alembic.config.Config("alembic.ini")
        cfg_ok = os.path.exists(cfg.config_file_name or "")
        results.append(("Alembic config found", cfg_ok, "alembic.ini" if cfg_ok else "missing"))
    except Exception as exc:  # noqa: BLE001
        results.append(("Alembic config", False, str(exc)))

    return results


def main() -> int:
    env = load_env()
    results = asyncio.run(check(env))
    all_pass = True
    print(f"\nCivicAgent Database Verification ({len(results)} checks)\n")
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        all_pass = all_pass and ok
        print(f"[{status}] {name}: {detail}")
    print("")
    print("RESULT:", "PASS" if all_pass else "FAIL")
    return 0 if all_pass else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
