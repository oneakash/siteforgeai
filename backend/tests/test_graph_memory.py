"""Memory inside the workflow (scenarios 8 & 9 + resilience)."""

import pytest

from app.demo.demo_embedder import DemoEmbedder
from app.demo.demo_llm import DemoLLM
from app.graph import service
from app.memory.provider import StaticEmbedderProvider
from app.memory.service import MemoryService
from tests import sample_data as sd
from tests.graph_env import make_env, q

pytestmark = pytest.mark.asyncio


class Broken:
    async def get(self, project_id=None):
        raise RuntimeError("embedding provider down")


async def start(g, deps, user="mem-u1"):
    return await service.start_project(
        g, deps, user_id=user, brand_name="Aurum Escapes", prompt="Luxury travel", niche="Travel"
    )


async def facts(pid):
    return {
        r[0]: (r[1], r[2], r[3])
        for r in await q(
            "SELECT topic_key, content, version, (embedding IS NOT NULL) FROM memories WHERE project_id=%s AND is_active AND topic_key IS NOT NULL",
            (pid,),
        )
    }


async def test_research_becomes_memory_but_unapproved_brand_does_not():
    async with make_env(DemoLLM()) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
    f = await facts(pid)
    assert {
        "research.niche",
        "research.audience",
        "research.competitors",
        "research.seo.keywords",
        "research.seo.pages",
    } <= set(f)
    assert not [t for t in f if t.startswith("brand.")]  # a DRAFT guideline is not memory
    assert all(v[2] for v in f.values())  # embedded with the active model


async def test_s9_approved_brand_is_memorised_and_revision_history_is_clean():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        await service.resume(
            g, deps, pid, {"action": "revise", "feedback": "More premium: dark green and gold."}
        )
        out = await service.resume(g, deps, pid, {"action": "approve"})
    f = await facts(pid)
    assert (
        "#0B3D2E" in f["brand.palette"][0] and "#1D3557" not in f["brand.palette"][0]
    )  # only the APPROVED revision
    assert len([t for t in f if t.startswith("brand.")]) == 8
    assert {"architecture.sitemap", "architecture.navigation", "architecture.ctas"} <= set(
        f
    )  # wireframe stage
    texts = [
        r[0]
        for r in await q(
            "SELECT content FROM memories WHERE project_id=%s AND kind='decision' AND is_active",
            (pid,),
        )
    ]
    assert any(
        "dark green and gold" in t and "brand_guideline" in t for t in texts
    )  # the user's decision is remembered
    assert any("approved brand guideline revision 2" in t for t in texts)
    # no topic ever has two active rows
    assert not await q(
        "SELECT topic_key FROM memories WHERE project_id=%s AND is_active AND topic_key IS NOT NULL GROUP BY 1 HAVING count(*)>1",
        (pid,),
    )


async def test_agents_receive_only_their_relevant_memories():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        await service.resume(
            g, deps, pid, {"action": "revise", "feedback": "More premium: dark green and gold."}
        )
        brand_r2_prompt = llm.last_messages["BrandGuideline"][-1]["content"]  # the revision run
        await service.resume(g, deps, pid, {"action": "approve"})
    assert (
        '<memory kind="decision">' in brand_r2_prompt and "dark green and gold" in brand_r2_prompt
    )  # decision recalled into the revision
    wf = llm.last_messages["Wireframe"][-1]["content"]
    for topic in ("brand.palette", "brand.typography", "brand.personality"):
        assert f'<memory kind="{topic}">' in wf  # pinned: approved brand always present
    assert "#0B3D2E" in wf
    assert 'kind="research.' not in wf  # research is NOT dumped into the wireframe (digest is)
    niche_prompt = llm.last_messages["NicheReport"][-1]["content"]
    assert "<memory" not in niche_prompt  # first-run research gets no stale context
    audit = await q(
        "SELECT payload->>'agent' FROM audit_log WHERE project_id=%s AND action='memory_recalled'",
        (pid,),
    )
    assert ("wireframe",) in audit  # traceable: which agent saw memory


async def test_s8_session_memory_clarification_is_scoped_to_this_session():
    llm = DemoLLM(scripts={"BrandFeedbackTriage": [sd.triage_unsure(), sd.triage_brand_only()]})
    async with make_env(llm) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        await service.resume(g, deps, pid, {"action": "revise", "feedback": "I don't like it"})
        await service.resume(g, deps, pid, {"answer": "darker please"})
    rows = await q(
        "SELECT scope, session_id, content FROM memories WHERE project_id=%s AND kind='clarification'",
        (pid,),
    )
    assert rows == [
        ("session", f"proj-{pid}", "Q: Do you want a lighter or a darker look? A: darker please")
    ]


async def test_user_preferences_follow_the_user_into_new_projects_only():
    llm = DemoLLM()
    async with make_env(llm) as (g, deps):
        async with deps.conn() as conn:
            await deps.memory.add_preference(
                conn,
                user_id="mem-pref",
                text="Always prefers premium dark themes for travel brands",
            )
        await start(g, deps, user="mem-pref")
        mine = llm.last_messages["PlanDraft"][-1]["content"]
        await start(g, deps, user="mem-other")
        theirs = llm.last_messages["PlanDraft"][-1]["content"]
    assert 'kind="preference"' in mine and "premium dark themes" in mine
    assert "premium dark themes" not in theirs
    import psycopg

    from app.config import DATABASE_URL

    with psycopg.connect(DATABASE_URL, autocommit=True) as c:
        c.execute("DELETE FROM memories WHERE user_id IN ('mem-pref','mem-other')")


async def test_embedding_outage_never_breaks_the_workflow_and_can_be_repaired():
    llm = DemoLLM()
    async with make_env(llm, memory=MemoryService(Broken())) as (g, deps):
        out = await start(g, deps)
        pid = out["project_id"]
        assert out["waiting_for"]["type"] == "brand_review"  # workflow unaffected
        out = await service.resume(g, deps, pid, {"action": "approve"})
        assert out["phase"] == "wireframe_complete"
    f = await facts(pid)
    assert "brand.palette" in f and not any(
        v[2] for v in f.values()
    )  # text stored, vectors pending
    wf = llm.last_messages["Wireframe"][-1]["content"]
    assert '<memory kind="brand.palette">' in wf  # pinned recall worked WITHOUT embeddings
    w = await q(
        "SELECT payload->>'without_embedding' FROM audit_log WHERE project_id=%s AND action='memory_written' LIMIT 1",
        (pid,),
    )
    assert int(w[0][0]) > 0
    # provider recovers -> rebuild
    import psycopg

    from app.config import DATABASE_URL
    from app.memory.store import reembed_stale

    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        assert await reembed_stale(conn, DemoEmbedder("demo:bow")) >= len(f)
    assert all(v[2] for v in (await facts(pid)).values())


async def test_a_memory_backend_crash_is_logged_not_fatal():
    class Exploding(MemoryService):
        async def write_research(self, *a, **k):
            raise RuntimeError("boom")

    async with make_env(DemoLLM(), memory=Exploding(StaticEmbedderProvider(DemoEmbedder()))) as (
        g,
        deps,
    ):
        out = await start(g, deps)
        pid = out["project_id"]
    assert out["waiting_for"]["type"] == "brand_review"
    assert (
        await q(
            "SELECT count(*) FROM audit_log WHERE project_id=%s AND action='memory_error'", (pid,)
        )
    )[0][0] == 1
