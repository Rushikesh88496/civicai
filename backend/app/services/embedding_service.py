"""Local text-embedding service for duplicate correlation (Part 9).

Wraps ``fastembed`` (local Sentence Transformers via onnxruntime) to turn a
complaint's text into a fixed-width vector that is stored in pgvector and used
by the correlation agent for semantic similarity. The embedder is loaded lazily
(only on first use) and is intentionally *overridable* so tests can inject a
deterministic fake without downloading/loading the ONNX model.

The heavy synchronous inference runs in a threadpool (``asyncio.to_thread``) so
it never blocks the async event loop.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)

_WHITESPACE = re.compile(r"\s+")


class Embedder(Protocol):
    """Minimal embedding interface the correlation agent depends on."""

    def embed(self, text: str) -> list[float]: ...


@dataclass
class EmbeddingMeta:
    provider: str
    model: str
    dimensions: int


class LocalFastEmbed:
    """Embedder backed by ``fastembed`` (BAAI/bge-small-en, 384-dim)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._cfg = settings or get_settings()
        self._model_name = self._cfg.EMBEDDING_MODEL
        self._dim = int(self._cfg.EMBEDDING_DIM)
        self._cache_dir = (self._cfg.EMBEDDING_CACHE_DIR or "").strip() or None
        self._backend = None

    @property
    def provider(self) -> str:
        return "fastembed"

    @property
    def meta(self) -> EmbeddingMeta:
        return EmbeddingMeta(
            provider=self.provider,
            model=self._model_name,
            dimensions=self._dim,
        )

    def _get_backend(self):
        if self._backend is None:
            from fastembed import TextEmbedding  # deferred heavy import

            kwargs: dict = {"model_name": self._model_name}
            if self._cache_dir:
                kwargs["cache_dir"] = self._cache_dir
            self._backend = TextEmbedding(**kwargs)
            logger.info("Loaded embedding model %s (dim=%s)", self._model_name, self._dim)
        return self._backend

    def embed(self, text: str) -> list[float]:
        vec = next(self._get_backend().embed([text]))
        return [float(v) for v in vec]


def _normalize_text(description: str, category: str | None) -> str:
    """Normalize complaint text for consistent, comparable embeddings."""
    parts = [description]
    if category:
        parts.append(f"category: {category}")
    return _WHITESPACE.sub(" ", " ".join(parts)).strip().lower()


class EmbeddingService:
    """Facade that produces + metadata about complaint embeddings."""

    def __init__(self, embedder: Embedder | None = None, settings: Settings | None = None) -> None:
        self._cfg = settings or get_settings()
        self._embedder = embedder or LocalFastEmbed(self._cfg)

    @property
    def meta(self) -> EmbeddingMeta:
        if isinstance(self._embedder, LocalFastEmbed):
            return self._embedder.meta
        return EmbeddingMeta(
            provider="fake",
            model="test",
            dimensions=int(self._cfg.EMBEDDING_DIM),
        )

    async def embed_complaint_text(self, description: str, category: str | None) -> list[float]:
        """Embed complaint text, offloading the CPU inference to a threadpool."""
        text = _normalize_text(description, category)
        return list(await asyncio_to_thread(self._embedder.embed, text))

    async def embed_text(self, text: str) -> list[float]:
        """Embed arbitrary text (e.g. knowledge-base documents, Part 25)."""
        return list(await asyncio_to_thread(self._embedder.embed, text))


async def asyncio_to_thread(fn, *args, **kwargs):
    """Run ``fn`` in a worker thread (alias so import stays light)."""
    import asyncio

    return await asyncio.to_thread(fn, *args, **kwargs)
