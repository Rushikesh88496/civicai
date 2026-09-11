"""Filesystem-backed storage (default backend, no external service)."""

from __future__ import annotations

import os

from app.core.config import Settings
from app.core.media_signing import sign_media_token
from app.storage.base import Storage


class LocalStorage(Storage):
    """Stores objects as plain files under ``STORAGE_LOCAL_DIR``.

    The local directory is resolved relative to the backend working directory
    (the repository root when the app is started from ``backend/``).
    """

    def __init__(self, settings: Settings) -> None:
        root = settings.STORAGE_LOCAL_DIR
        self._root = os.path.abspath(root)
        self._settings = settings
        os.makedirs(self._root, exist_ok=True)

    @property
    def backend_name(self) -> str:
        return "local"

    def _path(self, key: str) -> str:
        # Guard against path traversal in an attacker-controlled key.
        normalized = os.path.normpath(key)
        if normalized.startswith(("..", "/", "\\")) or ":" in normalized:
            raise ValueError("Invalid storage key")
        full = os.path.join(self._root, normalized)
        if not os.path.normpath(full).startswith(os.path.normpath(self._root)):
            raise ValueError("Invalid storage key")
        return full

    def full_path(self, key: str) -> str:
        """Resolve a storage key to its absolute path (raises on traversal)."""
        return self._path(key)

    def upload(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return self.url(key)

    def delete(self, key: str) -> None:
        path = self._path(key)
        if os.path.exists(path):
            os.remove(path)

    def exists(self, key: str) -> bool:
        try:
            return os.path.isfile(self._path(key))
        except ValueError:
            return False

    def read(self, key: str) -> bytes:
        with open(self._path(key), "rb") as handle:
            return handle.read()

    def url(self, key: str) -> str:
        token = sign_media_token(
            key,
            secret=self._settings.JWT_SECRET,
            ttl_seconds=self._settings.MEDIA_ACCESS_TTL_SECONDS,
        )
        return f"/media/{key}?token={token}"
