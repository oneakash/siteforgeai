import os
import uuid

import psycopg
import pytest

from app.config import DATABASE_URL, EMBEDDING_DIM
from app.llm.embeddings import _check, build_embedder, normalize
from app.llm.router import ProviderConfigError
from tests.fakes import FakeEmbedder


def test_normalize_and_dimension_guard():
    v = normalize([3.0, 4.0]); assert v == pytest.approx([0.6, 0.8])
    with pytest.raises(ValueError, match="3072 dims"):
        _check([[0.1] * 3072], "google:gemini-embedding-2")          # un-truncated Gemini output must be rejected
    assert len(_check([[1.0] * EMBEDDING_DIM], "x")[0]) == EMBEDDING_DIM


def test_build_embedder_errors(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(ProviderConfigError, match="GOOGLE_API_KEY"):
        build_embedder("google:gemini-embedding-2")
    with pytest.raises(ProviderConfigError, match="no embedding adapter"):
        build_embedder("groq:whatever")


def test_build_gemini_embedder_pins_1536_dims_and_task_types(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    e = build_embedder("google:gemini-embedding-2")
    assert e.ref == "google:gemini-embedding-2" and e.dim == 1536
    assert e._doc.output_dimensionality == 1536 and e._doc.task_type == "RETRIEVAL_DOCUMENT"
    assert e._query.task_type == "RETRIEVAL_QUERY"


try:
    with psycopg.connect(DATABASE_URL, connect_timeout=2):
        pass
except Exception:
    pytest.skip("Postgres not reachable", allow_module_level=True)

from app.memory.store import add_memory, count_stale, reembed_stale, search_memories  # noqa: E402


@pytest.fixture
async def conn():
    c = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
    yield c
    await c.close()


@pytest.fixture
async def project(conn):
    pid = (await (await conn.execute(
        "INSERT INTO projects (user_id, brand_name, prompt, niche, thread_id) VALUES ('t','B','p','n',%s) RETURNING id",
        (f"t-{uuid.uuid4()}",))).fetchone())[0]
    yield pid
    await conn.execute("DELETE FROM projects WHERE id=%s", (pid,))


async def test_switching_embedding_model_isolates_then_reembed_restores_search(conn, project):
    old, new = FakeEmbedder("google:old-model"), FakeEmbedder("google:gemini-embedding-2")
    await add_memory(conn, old, user_id="t", project_id=project, kind="brand_decision",
                     content="palette is dark green and gold premium")
    await add_memory(conn, old, user_id="t", project_id=project, kind="audience",
                     content="couples planning honeymoon travel")
    hit = await search_memories(conn, old, project_id=project, query="dark green gold palette", k=1)
    assert hit[0][0] == "brand_decision" and hit[0][2] > 0.3

    # user switches to Gemini embeddings: old vectors live in a different space => must NOT be compared
    assert await search_memories(conn, new, project_id=project, query="dark green gold palette") == []
    assert await count_stale(conn, new, project) == 2

    assert await reembed_stale(conn, new, batch=1) >= 2                  # batches of 1 prove resumability
    assert await count_stale(conn, new, project) == 0
    hit = await search_memories(conn, new, project_id=project, query="dark green gold palette", k=1)
    assert hit[0][0] == "brand_decision"
    kinds_only = await search_memories(conn, new, project_id=project, query="travel", kinds=["audience"])
    assert [k for k, _, _ in kinds_only] == ["audience"]
