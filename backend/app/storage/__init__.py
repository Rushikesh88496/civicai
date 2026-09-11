"""Object storage backends for uploaded media.

Binaries (images / short videos) are stored outside PostgreSQL in an
object-store. Two backends are provided:

* ``local`` — writes files under ``STORAGE_LOCAL_DIR`` on disk. This is the
  default and needs no external service, so uploads work out of the box.
* ``s3`` — stores objects in a MinIO / S3-compatible bucket via ``boto3``.

The active backend is chosen at runtime by ``STORAGE_BACKEND`` and exposed
through :func:`get_storage`. Platform code should rely solely on the
:class:`Storage` interface and never touch backend specifics.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.storage.base import Storage
from app.storage.local import LocalStorage
from app.storage.s3 import S3Storage

__all__ = ["Storage", "get_storage"]

_storage: Storage | None = None


def get_storage(settings: Settings | None = None) -> Storage:
    """Return the application-wide storage backend (cached singleton)."""
    global _storage
    if _storage is None:
        cfg = settings or get_settings()
        if cfg.STORAGE_BACKEND.lower() == "s3":
            _storage = S3Storage(cfg)
        else:
            _storage = LocalStorage(cfg)
    return _storage
