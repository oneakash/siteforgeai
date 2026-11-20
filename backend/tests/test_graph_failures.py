import pytest

from app.agents.errors import TransientAgentError
from app.demo.demo_llm import DemoLLM
from app.graph import service
from tests import sample_data as sd
from tests.graph_env import make_env, q

pytestmark = pytest.mark.asyncio


async def start(g, deps):
    return await service.start_project(
        g, deps, user_id="u1", brand_name="Aurum Escapes", prompt="p", niche="Travel"
    )


async def test_transient_errors_are_retried_by_langgraph_policy():
    llm = DemoLLM(scripts={"SEOStrategy": [TransientAgentError("429"), TransientAgentError("503")]})
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
    assert (
        out["waiting_for"]["type"] == "brand_review" and llm.count("SEOStrategy") == 3
    )  # 2 failures + success
    assert llm.count("NicheReport") == 1  # siblings NOT re-run


async def test_invalid_output_is_corrected_in_loop_then_manager_retries_failed_task():
    bad = {"nope": 1}
    # 3 invalid answers exhaust run_agent's corrections -> task FAILED -> Manager retries with the errors as guidance
    llm = DemoLLM(scripts={"AudienceReport": [bad, bad, bad]})
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
    assert out["waiting_for"]["type"] == "brand_review"
    assert llm.count("AudienceReport") == 4  # 3 rejected + 1 good on the manager's retry
    assert llm.count("NicheReport") == 1
    attempts = (
        await q("SELECT attempts FROM tasks WHERE project_id=%s AND task_key='audience'", (pid,))
    )[0][0]
    assert attempts == 2
    assert (
        await q(
            "SELECT count(*) FROM audit_log WHERE project_id=%s AND action='task_failed'", (pid,)
        )
    )[0][0] == 1
    assert (
        await q(
            "SELECT count(*) FROM artifacts WHERE project_id=%s AND kind='audience_report'", (pid,)
        )
    )[0][0] == 1  # no junk stored


async def test_exhausted_retries_ask_user_who_can_skip():
    bad = {"nope": 1}
    llm = DemoLLM(scripts={"AudienceReport": [bad] * 20})
    async with make_env(llm, max_task_attempts=2) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        w = out["waiting_for"]
        assert (
            w["type"] == "task_failed"
            and w["task_key"] == "audience"
            and w["options"] == ["retry", "skip"]
        )
        out = await service.resume(g, deps, pid, {"action": "skip"})
    # brand proceeds without the skipped research; user still gets the approval checkpoint
    assert out["waiting_for"]["type"] == "brand_review"
    st = {t["key"]: t["status"] for t in out["tasks"]}
    assert st["audience"] == "skipped" and st["brand"] == "completed"
    assert (
        await q("SELECT status FROM tasks WHERE project_id=%s AND task_key='audience'", (pid,))
    )[0][0] == "skipped"


async def test_exhausted_transient_retries_leave_workflow_resumable():
    llm = DemoLLM(scripts={"SEOStrategy": [TransientAgentError("down")] * 3})
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        assert "error" in out and out["waiting_for"] is None
        # operator switches model / provider recovers => just continue
        out = await service.continue_run(g, deps, pid)
    assert out["waiting_for"]["type"] == "brand_review"
    assert (
        llm.count("NicheReport") == 1 and llm.count("SEOStrategy") == 4
    )  # finished siblings were not re-run
    assert (
        await q(
            "SELECT count(*) FROM audit_log WHERE project_id=%s AND action='workflow_error'", (pid,)
        )
    )[0][0] == 1


async def test_plan_without_brand_dependency_on_research_is_rejected_and_corrected():
    bad = sd.plan_draft()
    bad["tasks"][4]["depends_on"] = ["niche"]  # brand ignores audience/competitors/seo
    llm = DemoLLM(scripts={"PlanDraft": [bad]})
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
    assert llm.count("PlanDraft") == 2 and out["waiting_for"]["type"] == "brand_review"
