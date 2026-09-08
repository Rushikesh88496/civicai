from urllib.parse import urlparse

from app.core.config import get_settings

settings = get_settings()


def connection_meta(database_url: str) -> dict[str, str | int]:
    """Return non-sensitive connection metadata from a database URL.

    Never includes the username or password.
    """
    parsed = urlparse(database_url)
    return {
        "host": parsed.hostname or "localhost",
        "port": parsed.port or 5432,
        "database": parsed.path.lstrip("/") or "",
    }


def current_database_meta() -> dict[str, str | int]:
    return connection_meta(settings.DATABASE_URL)
