"""Resolves the ACTIVE embedder on every call, so switching the embedding model
(PUT /v1/models/overrides purpose=embedding) takes effect without a restart."""
from typing import Awaitable, Callable, Sequence

from app.config import DEFAULT_EMBEDDING_REF
from app.llm.embeddings import Embedder, build_embedder
from app.llm.router import OverrideRow, fetch_overrides_pg, pick_override


class EmbedderProvider:
    def __init__(self, fetch_overrides: Callable[[str | None], Awaitable[Sequence[OverrideRow]]] = fetch_overrides_pg,
                 default_ref: str = DEFAULT_EMBEDDING_REF, factory: Callable[[str], Embedder] = build_embedder):
        self._fetch, self._default, self._factory = fetch_overrides, default_ref, factory
        self._cache: dict[str, Embedder] = {}

    async def get(self, project_id: str | None = None) -> Embedder:
        pid = str(project_id) if project_id else None
        rows = await self._fetch(pid)
        ref = pick_override(rows, project_id=pid, agent=None, tier=None, purpose="embedding") or self._default
        if ref not in self._cache:
            self._cache[ref] = self._factory(ref)   # may raise ProviderConfigError (no key): callers degrade gracefully
        return self._cache[ref]


class StaticEmbedderProvider:
    """Fixed embedder (demo + tests)."""

    def __init__(self, embedder: Embedder):
        self._e = embedder

    async def get(self, project_id: str | None = None) -> Embedder:
        return self._e
