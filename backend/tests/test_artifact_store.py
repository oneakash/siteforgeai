"""Needs the Step 1 Postgres (DATABASE_URL). Skipped automatically if unreachable."""

import uuid

import psycopg
import pytest

from app.agents.execute import execute_task
from app.agents.llm import FakeLLM
from app.agents.registry import AGENTS
from app.config import DATABASE_URL
from app.contracts import BrandGuideline, ExecutionPlan
from app.store.artifacts import approve_artifact, load_latest, save_artifact
from tests import sample_data as sd

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=2):
        pass
except Exception:  # pragma: no cover
    pytest.skip("Postgres not reachable", allow_module_level=True)


@pytest.fixture
async def conn():
    c = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
    yield c
    await c.close()


@pytest.fixture
async def project(conn):
    pid = (
        await (
            await conn.execute(
                "INSERT INTO projects (user_id, brand_name, prompt, niche, thread_id) VALUES ('t','B','p','n',%s) RETURNING id",
                (f"t-{uuid.uuid4()}",),
            )
        ).fetchone()
    )[0]
    yield pid
    await conn.execute("DELETE FROM projects WHERE id=%s", (pid,))  # cascades


async def new_task(conn, pid, key="brand", agent="brand_guideline"):
    return (
        await (
            await conn.execute(
                "INSERT INTO tasks (project_id, task_key, agent) VALUES (%s,%s,%s) RETURNING id",
                (pid, key, agent),
            )
        ).fetchone()
    )[0]


async def test_versions_increment_and_load_latest_validates(conn, project):
    b = BrandGuideline.model_validate(sd.brand())
    a1 = await save_artifact(conn, project_id=project, kind="brand_guideline", content=b)
    b2 = b.model_copy(update={"revision": 2})
    a2 = await save_artifact(conn, project_id=project, kind="brand_guideline", content=b2)
    assert (a1.version, a2.version) == (1, 2)
    latest = await load_latest(conn, project, "brand_guideline")
    assert latest.version == 2 and latest.content.revision == 2
    await approve_artifact(conn, a2.id)
    assert (await load_latest(conn, project, "brand_guideline", approved_only=True)).version == 2


async def test_same_task_double_write_is_noop(conn, project):
    tid = await new_task(conn, project)
    b = BrandGuideline.model_validate(sd.brand())
    first = await save_artifact(
        conn, project_id=project, task_id=tid, kind="brand_guideline", content=b
    )
    again = await save_artifact(
        conn,
        project_id=project,
        task_id=tid,
        kind="brand_guideline",
        content=b.model_copy(update={"revision": 9}),
    )
    assert first.created_now and not again.created_now
    assert again.id == first.id and again.content.revision == 1  # original untouched
    n = (
        await (
            await conn.execute("SELECT count(*) FROM artifacts WHERE project_id=%s", (project,))
        ).fetchone()
    )[0]
    assert n == 1


async def test_execute_task_skips_llm_when_artifact_exists(conn, project):
    tid = await new_task(conn, project)
    llm = FakeLLM([sd.brand()])
    kw = {
        "project_id": project,
        "task_id": tid,
        "spec": AGENTS["brand_guideline"],
        "llm": llm,
        "inputs": {"brand_name": "Aurum Escapes"},
    }
    r1 = await execute_task(conn, **kw)
    r2 = await execute_task(conn, **kw)  # simulates re-entry after crash
    assert not r1.skipped and r2.skipped and len(llm.calls) == 1  # LLM called exactly once
    assert r1.artifact.id == r2.artifact.id


async def test_invalid_output_is_never_persisted(conn, project):
    from app.agents.errors import AgentOutputError

    tid = await new_task(conn, project)
    with pytest.raises(AgentOutputError):
        await execute_task(
            conn,
            project_id=project,
            task_id=tid,
            spec=AGENTS["brand_guideline"],
            llm=FakeLLM([{"bad": 1}] * 3),
            inputs={},
        )
    n = (
        await (
            await conn.execute("SELECT count(*) FROM artifacts WHERE project_id=%s", (project,))
        ).fetchone()
    )[0]
    assert n == 0


async def test_manager_plan_draft_converted_and_stored_as_execution_plan(conn, project):
    tid = await new_task(conn, project, "plan", "manager")
    await execute_task(
        conn,
        project_id=project,
        task_id=tid,
        spec=AGENTS["manager.plan"],
        llm=FakeLLM([sd.plan_draft()]),
        inputs={"prompt": "luxury travel"},
        to_artifact=lambda d: ExecutionPlan.from_draft(d),
        kind="execution_plan",
    )
    stored = await load_latest(conn, project, "execution_plan")
    assert (
        isinstance(stored.content, ExecutionPlan)
        and stored.content.tasks[0].status.value == "pending"
    )
