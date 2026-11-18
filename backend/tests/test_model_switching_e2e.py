"""Real Postgres: override table + migration + API + audit trail."""
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.agents.execute import execute_task
from app.agents.registry import AGENTS
from app.config import DATABASE_URL, DEFAULT_CHAT_REFS
from app.llm.router import ModelRouter
from tests import sample_data as sd
from tests.fakes import FakeChat

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=2):
        pass
except Exception:
    pytest.skip("Postgres not reachable", allow_module_level=True)


@pytest.fixture
async def conn():
    c = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
    yield c
    await c.close()


@pytest.fixture
async def project(conn):
    pid = (await (await conn.execute(
        "INSERT INTO projects (user_id, brand_name, prompt, niche, thread_id) VALUES ('t','Aurum Escapes','p','n',%s) RETURNING id",
        (f"t-{uuid.uuid4()}",))).fetchone())[0]
    yield pid
    await conn.execute("DELETE FROM projects WHERE id=%s", (pid,))
    await conn.execute("DELETE FROM model_overrides WHERE model_ref LIKE 'groq:test-%'")


async def task(conn, pid, key):
    return (await (await conn.execute(
        "INSERT INTO tasks (project_id, task_key, agent) VALUES (%s,%s,'brand_guideline') RETURNING id", (pid, key))).fetchone())[0]


async def test_api_switch_changes_model_for_next_task_and_is_audited(conn, project, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "x")
    seen = []
    router = ModelRouter(chat_factory=lambda ref: FakeChat(ref, payload=sd.brand(), calls=seen), fallbacks=[])  # real DB resolver
    run = lambda tid: execute_task(conn, project_id=project, task_id=tid, spec=AGENTS["brand_guideline"], llm=router,
                                   inputs={"brand_name": "Aurum Escapes"})
    with TestClient(__import__("app.main", fromlist=["app"]).app) as api:
        r1 = await run(await task(conn, project, "t1"))
        assert r1.model == DEFAULT_CHAT_REFS["reasoning"]                        # configured default (brand = reasoning tier)

        assert api.put("/v1/models/overrides", json={"model_ref": "bogus", "project_id": str(project)}).status_code == 400
        assert api.put("/v1/models/overrides", json={"model_ref": "groq:test-x", "agent": "nope"}).status_code == 400
        monkeypatch.delenv("GROQ_API_KEY")
        assert api.put("/v1/models/overrides", json={"model_ref": "groq:test-x", "project_id": str(project)}).status_code == 400  # key missing
        monkeypatch.setenv("GROQ_API_KEY", "x")
        ok = api.put("/v1/models/overrides", json={"model_ref": "groq:test-x", "project_id": str(project)})
        assert ok.status_code == 200

        r2 = await run(await task(conn, project, "t2"))
        assert r2.model == "groq:test-x"                                        # no restart needed
        cfg = api.get("/v1/models").json()
        assert any(o["model_ref"] == "groq:test-x" for o in cfg["overrides"])
        assert cfg["providers"]["groq"]["configured"] is True

        assert api.delete("/v1/models/overrides", params={"project_id": str(project)}).json()["deleted"] == 1
        r3 = await run(await task(conn, project, "t3"))
        assert r3.model == DEFAULT_CHAT_REFS["reasoning"]                        # back to the configured default

    rows = await (await conn.execute(
        "SELECT payload->>'model' FROM audit_log WHERE project_id=%s AND action='agent_completed' ORDER BY id", (project,))).fetchall()
    assert [r[0] for r in rows][1] == "groq:test-x"                            # audit trail records the model per artifact


def test_embedding_override_must_be_global(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "x")
    with TestClient(__import__("app.main", fromlist=["app"]).app) as api:
        pid = str(uuid.uuid4())
        for scope in ({"project_id": pid}, {"agent": "qa"}, {"tier": "fast"}):
            r = api.put("/v1/models/overrides", json={"model_ref": "google:gemini-embedding-2", "purpose": "embedding", **scope})
            assert r.status_code == 400 and "system-wide" in r.json()["detail"]
