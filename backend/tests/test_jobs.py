"""Queue-job semantics on a real Postgres checkpointer: idempotent, crash-safe, stale-safe."""

import uuid

import pytest

from app.config import DATABASE_URL
from app.demo.demo_llm import DemoLLM
from app.graph import service
from app.store.locks import project_lock
from tests.graph_env import make_env, q

pytestmark = pytest.mark.asyncio
RESEARCH = ["NicheReport", "AudienceReport", "CompetitorReport", "SEOStrategy"]
REVISE = {"action": "revise", "feedback": "More premium: dark green and gold."}


async def new_project() -> str:
    pid = str(uuid.uuid4())
    await q(
        "INSERT INTO projects (id, user_id, brand_name, prompt, niche, thread_id) "
        "VALUES (%s,'u1','Aurum Escapes','Luxury private travel agency','Travel',%s) RETURNING id",
        (pid, f"proj-{pid}"),
    )
    return pid


async def test_start_job_is_idempotent_on_redelivery():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        pid = await new_project()
        out = await service.run_job(g, deps, pid, mode="start")
        assert out["waiting_for"]["type"] == "brand_review"

        # the broker re-delivers the same job (worker died after finishing, before the ack)
        again = await service.run_job(g, deps, pid, mode="start")
        assert again["waiting_for"]["type"] == "brand_review"
        assert llm.count("PlanDraft") == 1
        assert all(llm.count(n) == 1 for n in RESEARCH)
        assert llm.count("BrandGuideline") == 1


async def test_stale_resume_is_dropped_and_fresh_resume_applies():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        pid = await new_project()
        await service.run_job(g, deps, pid, mode="start")
        token = await service.pending_resume_token(g, deps, pid)
        assert token

        out = await service.run_job(g, deps, pid, mode="resume", payload=REVISE, token=token)
        assert out["waiting_for"]["revision"] == 2 and llm.count("BrandGuideline") == 2
        assert await service.pending_resume_token(g, deps, pid) != token

        # double-click / duplicate delivery: same (now stale) token must NOT answer the new review
        out = await service.run_job(g, deps, pid, mode="resume", payload=REVISE, token=token)
        assert out["waiting_for"]["revision"] == 2 and llm.count("BrandGuideline") == 2
    actions = [r[0] for r in await q("SELECT action FROM audit_log WHERE project_id=%s", (pid,))]
    assert "stale_resume_dropped" in actions


async def test_continue_is_a_noop_while_waiting_for_the_user():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        pid = await new_project()
        await service.run_job(g, deps, pid, mode="start")
        out = await service.run_job(g, deps, pid, mode="continue")
        assert out["waiting_for"]["type"] == "brand_review"
        assert llm.count("BrandGuideline") == 1


async def test_resume_before_start_is_rejected():
    async with make_env(DemoLLM()) as (g, deps):
        pid = await new_project()
        with pytest.raises(ValueError):
            await service.run_job(g, deps, pid, mode="resume", payload={"action": "approve"})


async def test_project_lock_is_exclusive_and_released():
    pid = str(uuid.uuid4())
    async with project_lock(DATABASE_URL, pid) as first:
        assert first is True
        async with project_lock(DATABASE_URL, pid) as second:
            assert second is False
    async with project_lock(DATABASE_URL, pid) as third:
        assert third is True
