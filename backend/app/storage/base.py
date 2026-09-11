"""Abstract object-storage interface shared by all backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Storage(ABC):
    """Minimal object-store contract used by the complaint media flow.

    Implementations must be safe for binary uploads and never store the
    payload in a relational database.
    """

    @abstractmethod
    def upload(self, key: str, data: bytes, content_type: str) -> str:
        """Persist ``data`` under ``key`` and return a URL to retrieve it."""
        raise NotImplementedError

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object identified by ``key`` (idempotent)."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Return True if an object exists at ``key``."""
        raise NotImplementedError

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Return the raw bytes stored at ``key`` (Part 8, vision reads images).

        Raises ``FileNotFoundError`` / an equivalent provider error when the
        object does not exist.
        """
        raise NotImplementedError

    @abstractmethod
    def url(self, key: str) -> str:
        """Return an (ideally public) URL for ``key``."""
        raise NotImplementedError
