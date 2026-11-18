import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import DATABASE_URL
from app.demo.demo_embedder import DemoEmbedder
from app.main import app
from app.memory.provider import StaticEmbedderProvider
from app.memory.service import MemoryService

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=2):
        pass
except Exception:
    pytest.skip("Postgres not reachable", allow_module_level=True)


def test_memory_endpoints_end_to_end():
    uid = f"mem-api-{uuid.uuid4()}"
    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        pid = str(c.execute("INSERT INTO projects (user_id, brand_name, prompt, niche, thread_id) VALUES (%s,'B','p','n',%s) RETURNING id",
                            (uid, f"t-{uuid.uuid4()}")).fetchone()[0])
    try:
        with TestClient(app) as api:
            app.state.memory = MemoryService(StaticEmbedderProvider(DemoEmbedder("demo:bow")))   # no API key needed
            assert api.get(f"/v1/projects/{uuid.uuid4()}/memories").status_code == 404
            assert api.post(f"/v1/users/{uid}/preferences", json={"text": "x"}).status_code == 422          # too short
            assert api.post(f"/v1/users/{uid}/preferences", json={"text": "Prefers dark luxe themes", "topic_key": "Bad Key"}).status_code == 422
            r = api.post(f"/v1/users/{uid}/preferences", json={"text": "Prefers dark luxe themes", "topic_key": "pref.theme"}).json()
            assert r["status"] == "created" and r["embedded"] is True
            r2 = api.post(f"/v1/users/{uid}/preferences", json={"text": "Prefers light airy themes", "topic_key": "pref.theme"}).json()
            assert r2["status"] == "superseded" and r2["version"] == 2                                       # changed mind => supersede
            hits = api.get(f"/v1/projects/{pid}/memories/search", params={"q": "light airy themes"}).json()
            assert [h["content"] for h in hits] == ["Prefers light airy themes"] and hits[0]["version"] == 2
            assert api.get(f"/v1/projects/{pid}/memories").json() == []                                       # user-level memory is not project data
            assert api.post("/v1/memories/reembed").json()["embedding_model"] == "demo:bow"
    finally:
        with psycopg.connect(DATABASE_URL, autocommit=True) as c:
            c.execute("DELETE FROM projects WHERE id=%s", (pid,))
            c.execute("DELETE FROM memories WHERE user_id=%s", (uid,))
