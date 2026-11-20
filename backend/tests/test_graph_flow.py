"""Acceptance scenarios 1-5 on a real Postgres checkpointer (LLM is deterministic)."""

import pytest

from app.demo.demo_llm import DemoLLM
from app.graph import service
from tests import sample_data as sd
from tests.graph_env import make_env, q

pytestmark = pytest.mark.asyncio
RESEARCH = ["NicheReport", "AudienceReport", "CompetitorReport", "SEOStrategy"]


async def start(g, deps):
    return await service.start_project(
        g,
        deps,
        user_id="u1",
        brand_name="Aurum Escapes",
        prompt="Luxury private travel agency",
        niche="Travel",
    )


async def test_s1_s2_s3_plan_parallel_research_consolidation_and_pause():
    llm = DemoLLM(delay=0.05)
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]

    # S1: structured, trackable plan with deps + ledger rows
    assert out["plan_version"] == 1
    tasks = {t["key"]: t for t in out["tasks"]}
    assert set(tasks) == {"niche", "audience", "competitors", "seo", "brand", "wireframe"}
    ledger = dict(await q("SELECT task_key, status FROM tasks WHERE project_id=%s", (pid,)))
    assert (
        ledger["plan"] == "completed"
        and ledger["brand"] == "completed"
        and ledger["wireframe"] == "pending"
    )
    assert (
        await q(
            "SELECT count(*) FROM artifacts WHERE project_id=%s AND kind='execution_plan'", (pid,)
        )
    )[0][0] == 1

    # S2: the four research agents ran CONCURRENTLY; Manager consolidated their outputs
    assert llm.max_in_flight == 4 and all(llm.count(n) == 1 for n in RESEARCH)
    digest = await q(
        "SELECT content FROM artifacts WHERE project_id=%s AND kind='research_digest'", (pid,)
    )
    assert (
        len(digest) == 1
        and digest[0][0]["competitors"][0] == "Black Tomato"
        and "/destinations" in digest[0][0]["recommended_pages"]
    )

    # S3: paused at the mandatory checkpoint; nothing downstream has run
    assert out["waiting_for"]["type"] == "brand_review" and out["phase"] == "waiting_for_approval"
    assert out["waiting_for"]["guideline"]["palette"]["primary"] == "#1D3557"
    assert tasks["wireframe"]["status"] == "pending" and llm.count("Wireframe") == 0
    assert out["next"] == ["brand_review"]


async def test_s4_s5_revise_reruns_only_brand_then_approve_resumes_without_repeating_research():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        # S4: "dark green and gold"
        out = await service.resume(
            g, deps, pid, {"action": "revise", "feedback": "More premium: dark green and gold."}
        )
        assert out["waiting_for"]["type"] == "brand_review"  # presented again; waits again
        assert out["waiting_for"]["revision"] == 2
        assert out["waiting_for"]["guideline"]["palette"]["primary"] == "#0B3D2E"
        assert all(llm.count(n) == 1 for n in RESEARCH)  # research NOT re-run
        assert llm.count("BrandGuideline") == 2 and llm.count("BrandFeedbackTriage") == 1
        st = {t["key"]: t["status"] for t in out["tasks"]}
        assert (
            st["brand"] == "superseded"
            and st["brand_r2"] == "completed"
            and st["wireframe"] == "pending"
        )
        assert out["plan_version"] == 2
        assert llm.count("Wireframe") == 0  # still blocked on approval

        # S5: approve => same execution resumes from the checkpoint
        out = await service.resume(g, deps, pid, {"action": "approve"})
    assert out["waiting_for"] is None and out["phase"] == "wireframe_complete"
    assert all(llm.count(n) == 1 for n in RESEARCH) and llm.count("Wireframe") == 1
    brand = await q(
        "SELECT version, approved FROM artifacts WHERE project_id=%s AND kind='brand_guideline' ORDER BY version",
        (pid,),
    )
    assert brand == [(1, False), (2, True)]  # only the approved revision is approved
    wf = await q("SELECT count(*) FROM artifacts WHERE project_id=%s AND kind='wireframe'", (pid,))
    assert wf[0][0] == 1
    actions = [
        r[0]
        for r in await q("SELECT action FROM audit_log WHERE project_id=%s ORDER BY id", (pid,))
    ]
    for a in (
        "plan_created",
        "research_consolidated",
        "brand_feedback",
        "feedback_triaged",
        "brand_approved",
        "stage_finished",
    ):
        assert a in actions  # full audit trail


async def test_audience_feedback_reruns_audience_and_brand_but_not_other_research():
    llm = DemoLLM(scripts={"BrandFeedbackTriage": [sd.triage_audience()]})
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        out = await service.resume(
            g, deps, pid, {"action": "revise", "feedback": "Target younger remote workers instead"}
        )
    assert out["waiting_for"]["type"] == "brand_review"
    assert llm.count("AudienceReport") == 2 and llm.count("BrandGuideline") == 2
    assert all(llm.count(n) == 1 for n in ("NicheReport", "CompetitorReport", "SEOStrategy"))
    digests = await q(
        "SELECT version FROM artifacts WHERE project_id=%s AND kind='research_digest' ORDER BY version",
        (pid,),
    )
    assert [d[0] for d in digests] == [1, 2]  # digest rebuilt because research changed


async def test_clarification_interrupt_then_proceed():
    llm = DemoLLM(
        scripts={
            "BrandFeedbackTriage": [sd.triage_unsure(), sd.triage_brand_only("Make it darker.")]
        }
    )
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        out = await service.resume(
            g, deps, pid, {"action": "revise", "feedback": "I don't like it"}
        )
        assert out["waiting_for"] == {
            "type": "clarification",
            "question": "Do you want a lighter or a darker look?",
        }
        assert llm.count("BrandGuideline") == 1  # nothing re-run on a guess
        out = await service.resume(g, deps, pid, {"answer": "darker"})
    assert out["waiting_for"]["type"] == "brand_review" and out["waiting_for"]["revision"] == 2


async def test_resume_payload_is_validated_before_touching_the_graph():
    async with make_env(DemoLLM()) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        with pytest.raises(Exception):
            await service.resume(g, deps, pid, {"action": "revise", "feedback": "  "})
        with pytest.raises(Exception):
            await service.resume(g, deps, pid, {"action": "maybe"})
        assert (await service.status(g, deps, pid))["waiting_for"][
            "type"
        ] == "brand_review"  # still safely paused


async def test_threads_are_isolated_between_projects():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        a = await start(g, deps)
        b = await start(g, deps)
        await service.resume(g, deps, a["project_id"], {"action": "approve"})
        sb = await service.status(g, deps, b["project_id"])
    assert sb["waiting_for"]["type"] == "brand_review"  # B untouched by A's approval
