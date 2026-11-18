import hashlib
import math
import re

from app.config import EMBEDDING_DIM


class DemoEmbedder:
    """Bag-of-words hashing embedder (no API key). Different `ref` => different vector space,
    like two real embedding models."""

    def __init__(self, ref: str = "demo:bow"):
        self.ref, self.dim = ref, EMBEDDING_DIM

    def _v(self, text: str) -> list[float]:
        v = [0.0] * EMBEDDING_DIM
        for tok in re.findall(r"[a-z0-9#]+", text.lower()):
            v[int(hashlib.md5(f"{self.ref}|{tok}".encode()).hexdigest(), 16) % EMBEDDING_DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    async def embed_documents(self, texts):
        return [self._v(t) for t in texts]

    async def embed_query(self, text):
        return self._v(text)
