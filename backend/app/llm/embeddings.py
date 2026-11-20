"""Embedding providers. Dimension is pinned to the DB column (1536)."""

import math
import os
from collections.abc import Sequence
from typing import Protocol

from app.config import EMBEDDING_DIM
from app.llm.router import PROVIDERS, ModelRef, ProviderConfigError


class Embedder(Protocol):
    ref: str  # 'provider:model' - stored in memories.embedding_model
    dim: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...


def normalize(v: Sequence[float]) -> list[float]:
    """Gemini only auto-normalizes its full 3072-dim output; truncated (MRL)
    vectors must be normalized by us before cosine similarity."""
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _check(vecs: Sequence[Sequence[float]], ref: str) -> list[list[float]]:
    for v in vecs:
        if len(v) != EMBEDDING_DIM:
            raise ValueError(
                f"{ref} returned {len(v)} dims; the memories column is vector({EMBEDDING_DIM})"
            )
    return [normalize(v) for v in vecs]


class LangChainEmbedder:
    def __init__(self, ref: ModelRef):
        spec = PROVIDERS.get(ref.provider)
        if not spec or not spec.embeddings:
            raise ProviderConfigError(f"provider '{ref.provider}' has no embedding adapter")
        key = os.environ.get(spec.env_key)
        if not key:
            raise ProviderConfigError(f"{spec.env_key} is not set (needed for '{ref}')")
        self.ref, self.dim = str(ref), EMBEDDING_DIM
        if ref.provider == "openai":
            from langchain_openai import OpenAIEmbeddings

            self._doc = self._query = OpenAIEmbeddings(
                model=ref.model, api_key=key, dimensions=EMBEDDING_DIM
            )
        else:  # google
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            kw = {
                "model": ref.model,
                "google_api_key": key,
                "output_dimensionality": EMBEDDING_DIM,
            }
            self._doc = GoogleGenerativeAIEmbeddings(task_type="RETRIEVAL_DOCUMENT", **kw)
            self._query = GoogleGenerativeAIEmbeddings(task_type="RETRIEVAL_QUERY", **kw)

    async def embed_documents(self, texts):
        return _check(await self._doc.aembed_documents(list(texts)), self.ref)

    async def embed_query(self, text):
        return _check([await self._query.aembed_query(text)], self.ref)[0]


def build_embedder(ref_text: str) -> Embedder:
    return LangChainEmbedder(ModelRef.parse(ref_text))
