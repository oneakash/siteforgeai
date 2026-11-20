"""Memory lifecycle against real Postgres + pgvector."""

import uuid

import psycopg
import pytest

from app.config import DATABASE_URL
from app.contracts import BrandGuideline, Wireframe
from app.demo.demo_embedder import DemoEmbedder
from app.memory.extract import architecture_facts, brand_facts
from app.memory.provider import StaticEmbedderProvider
from app.memory.service import MemoryService
from app.memory.store import reembed_stale
from tests import sample_data as sd

try:
    with psycopg.connect(DATABASE_URL, connect_timeout=2):
        pass
except Exception:
    pytest.skip("Postgres not reachable", allow_module_level=True)


class Broken:
    async def get(self, project_id=None):
        raise RuntimeError("GOOGLE_API_KEY is not set")


def svc(ref="demo:bow", **kw):
    return MemoryService(StaticEmbedderProvider(DemoEmbedder(ref)), **kw)


@pytest.fixture
async def conn():
    c = await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True)
    yield c
    await c.close()


async def mk_project(conn, user="u1"):
    return (
        await (
            await conn.execute(
                "INSERT INTO projects (user_id, brand_name, prompt, niche, thread_id) VALUES (%s,'B','p','n',%s) RETURNING id",
                (user, f"t-{uuid.uuid4()}"),
            )
        ).fetchone()
    )[0]


@pytest.fixture
async def project(conn):
    pid = await mk_project(conn)
    yield pid
    await conn.execute("DELETE FROM projects WHERE id=%s", (pid,))
    await conn.execute("DELETE FROM memories WHERE user_id LIKE 'mem-test-%'")


async def active(conn, pid, topic):
    return await (
        await conn.execute(
            "SELECT content, version FROM memories WHERE project_id=%s AND topic_key=%s AND is_active",
            (pid, topic),
        )
    ).fetchall()


# ---------------------------------------------------------------- write: dedupe / supersede / contradictions
async def test_fact_lifecycle_create_duplicate_supersede(conn, project):
    s = svc()
    kw = {
        "scope": "project",
        "user_id": "u1",
        "project_id": project,
        "kind": "brand_decision",
        "topic_key": "brand.palette",
    }
    r1 = await s.remember(conn, content="Approved palette: primary #1D3557 navy", **kw)
    r2 = await s.remember(
        conn, content="approved PALETTE: primary #1d3557 navy!!", **kw
    )  # same after normalisation
    r3 = await s.remember(
        conn, content="Approved palette: primary #0B3D2E dark green and gold", **kw
    )
    assert (r1.status, r2.status, r3.status) == (
        "created",
        "duplicate",
        "superseded",
    ) and r2.id == r1.id
    assert r3.version == 2
    rows = await active(conn, project, "brand.palette")
    assert len(rows) == 1 and "#0B3D2E" in rows[0][0]  # ONE active, and it is the new one
    old = await (
        await conn.execute(
            "SELECT is_active, superseded_by, superseded_at IS NOT NULL FROM memories WHERE id=%s",
            (r1.id,),
        )
    ).fetchone()
    assert old == (False, r3.id, True)  # history chain preserved


async def test_database_itself_forbids_two_active_memories_for_one_topic(conn, project):
    s = svc()
    await s.remember(
        conn,
        scope="project",
        user_id="u1",
        project_id=project,
        kind="k",
        topic_key="t",
        content="one",
    )
    with pytest.raises(psycopg.errors.UniqueViolation):  # even a buggy writer cannot contradict
        await conn.execute(
            "INSERT INTO memories (user_id, project_id, scope, kind, topic_key, content) VALUES ('u1',%s,'project','k','t','two')",
            (project,),
        )


async def test_log_entries_suppress_exact_and_near_duplicates_but_keep_distinct_ones(conn, project):
    s = svc()
    mk = lambda t: s.log_decision(conn, user_id="u1", project_id=project, text=t)  # noqa: E731
    a = await mk("User wants a dark green and gold palette for the site")
    b = await mk(
        "user wants a dark green gold palette for the site"
    )  # near duplicate (cosine >= 0.92)
    c = await mk("Footer must include a newsletter signup form")
    assert (a.status, b.status, c.status) == ("created", "duplicate", "created") and b.id == a.id


async def test_scope_rules_and_isolation(conn, project):
    other = await mk_project(conn)
    ua, ub = f"mem-test-{uuid.uuid4()}", f"mem-test-{uuid.uuid4()}"
    s = svc()
    with pytest.raises(ValueError):  # scope/ids must agree
        await s.remember(
            conn, scope="user", user_id=ua, project_id=project, kind="preference", content="x"
        )
    with pytest.raises(ValueError):
        await s.remember(
            conn, scope="session", user_id=ua, project_id=project, kind="note", content="x"
        )
    await s.add_preference(conn, user_id=ua, text="Always prefers premium dark themes")
    await s.add_preference(conn, user_id=ub, text="Prefers bright playful pastel themes")
    await s.remember(
        conn,
        scope="project",
        user_id=ua,
        project_id=project,
        kind="decision",
        content="Project A secret pricing decision",
    )
    await s.remember(
        conn,
        scope="session",
        user_id=ua,
        project_id=project,
        session_id="sess-1",
        kind="note",
        content="session one note about themes",
    )
    q = {"user_id": ua, "query": "themes pricing note", "k": 10, "min_sim": 0.01}
    a = {m.content for m in await s.recall(conn, project_id=project, session_id="sess-1", **q)}
    assert "Always prefers premium dark themes" in a and "session one note about themes" in a
    assert "Project A secret pricing decision" in a
    assert "Prefers bright playful pastel themes" not in a  # other USER never leaks
    b = {m.content for m in await s.recall(conn, project_id=other, session_id="sess-2", **q)}
    assert b == {
        "Always prefers premium dark themes"
    }  # user-level follows the user; project/session do not
    await conn.execute("DELETE FROM projects WHERE id=%s", (other,))


# ---------------------------------------------------------------- read: pinned + semantic + filters
async def test_recall_pins_brand_facts_regardless_of_similarity_and_hides_superseded(conn, project):
    s = svc()
    bg1 = BrandGuideline.model_validate(sd.brand_original())
    bg2 = BrandGuideline.model_validate(sd.brand_revised()).model_copy(update={"revision": 3})
    await s.write_brand(conn, user_id="u1", project_id=project, guideline=bg1)
    await s.write_brand(
        conn, user_id="u1", project_id=project, guideline=bg2
    )  # later approved revision supersedes
    await s.log_decision(
        conn, user_id="u1", project_id=project, text="Customer wants testimonials near the top"
    )
    got = await s.recall(
        conn,
        project_id=project,
        user_id="u1",
        query="zebra quantum unrelated words",
        kinds=["decision"],
        pinned_topics=["brand.%"],
    )
    topics = {m.topic_key for m in got}
    assert {
        "brand.palette",
        "brand.typography",
        "brand.personality",
    } <= topics  # pinned even though query is unrelated
    pal = next(m for m in got if m.topic_key == "brand.palette")
    assert (
        "#0B3D2E" in pal.content and "#1D3557" not in pal.content and pal.version == 2
    )  # contradiction avoided
    assert all(m.is_active for m in got)
    sem = await s.recall(
        conn, project_id=project, user_id="u1", query="testimonials near top", kinds=["decision"]
    )
    assert [m.kind for m in sem] == ["decision"] and sem[0].similarity > 0.3


async def test_semantic_recall_filters_by_kind_metadata_and_min_similarity(conn, project):
    s = svc()
    await s.remember(
        conn,
        scope="project",
        user_id="u1",
        project_id=project,
        kind="decision",
        content="use serif headings",
        metadata={"revision": 2},
    )
    await s.remember(
        conn,
        scope="project",
        user_id="u1",
        project_id=project,
        kind="preference_note",
        content="use serif headings everywhere",
        metadata={"revision": 3},
    )
    base = {"project_id": project, "user_id": "u1", "query": "serif headings", "min_sim": 0.1}
    assert len(await s.recall(conn, **base)) == 2
    assert [m.kind for m in await s.recall(conn, kinds=["decision"], **base)] == ["decision"]
    assert [m.kind for m in await s.recall(conn, metadata_filter={"revision": 3}, **base)] == [
        "preference_note"
    ]
    assert (
        await s.recall(
            conn, project_id=project, user_id="u1", query="serif headings", min_sim=0.99999
        )
        == []
    )  # nothing is that close


# ---------------------------------------------------------------- resilience + embedding switch
async def test_embedding_outage_does_not_block_writes_and_pinned_recall_still_works(conn, project):
    down = MemoryService(Broken())
    r = await down.write_brand(
        conn,
        user_id="u1",
        project_id=project,
        guideline=BrandGuideline.model_validate(sd.brand_revised()),
    )
    assert len(r) == 8 and all(
        x.status == "created" and not x.embedded for x in r
    )  # text stored, vectors missing
    got = await down.recall(
        conn, project_id=project, user_id="u1", query="colors", pinned_topics=["brand.%"]
    )
    assert len(got) == 8 and all(
        m.similarity is None for m in got
    )  # consistency never depends on embeddings
    ok = svc()
    assert (
        await ok.recall(
            conn,
            project_id=project,
            user_id="u1",
            query="approved color palette",
            kinds=["brand_decision"],
        )
        == []
    )
    assert (
        await reembed_stale(conn, DemoEmbedder("demo:bow")) >= 8
    )  # provider is back: rebuild index
    hit = await ok.recall(
        conn,
        project_id=project,
        user_id="u1",
        query="approved color palette hex",
        kinds=["brand_decision"],
        k=1,
    )
    assert hit[0].topic_key == "brand.palette"


async def test_switching_embedding_model_isolates_old_vectors_until_reembed(conn, project):
    await svc("google:old").log_decision(
        conn, user_id="u1", project_id=project, text="Hero should be image-led"
    )
    new = svc("google:gemini-embedding-2")
    assert (
        await new.recall(
            conn, project_id=project, user_id="u1", query="hero image-led", min_sim=0.01
        )
        == []
    )
    await reembed_stale(conn, DemoEmbedder("google:gemini-embedding-2"))
    assert (
        len(
            await new.recall(
                conn, project_id=project, user_id="u1", query="hero image-led", min_sim=0.01
            )
        )
        == 1
    )


# ---------------------------------------------------------------- compression + summarization + extraction
def test_to_prompt_dedupes_truncates_and_respects_budget():
    from app.memory.types import Memory

    mk = lambda i, topic, txt, sim: Memory(uuid.uuid4(), "project", "k", topic, txt, 1, {}, sim)  # noqa: E731
    mems = [
        mk(1, "brand.palette", "P" * 900, None),
        mk(2, "brand.palette", "dup", None),
        mk(3, None, "A" * 300, 0.9),
        mk(4, None, "B" * 300, 0.5),
        mk(5, None, "C" * 300, 0.4),
    ]
    out = MemoryService.to_prompt(mems, budget_chars=1200, per_item=500)
    assert (
        out[0][0] == "brand.palette" and len(out[0][1]) == 500 and out[0][1].endswith("…")
    )  # pinned first, trimmed
    assert (
        sum(len(t) for _, t in out) <= 1200
        and len([o for o in out if o[0] == "brand.palette"]) == 1
    )


async def test_decision_log_is_summarized_when_it_grows_and_originals_are_archived(conn, project):
    from app.demo.demo_llm import DemoLLM

    s, llm = svc(), DemoLLM()
    for i in range(10):
        await s.log_decision(
            conn,
            user_id="u1",
            project_id=project,
            text=f"Decision number {i} about topic{i} xx{i*7} yy{i*13}",
        )
    r = await s.summarize_decisions(
        conn, llm, project_id=project, user_id="u1", min_items=8, keep_last=3
    )
    assert r and llm.count("MemorySummary") == 1
    act = await s.list_memories(conn, project_id=project, kind="decision")
    assert len(act) == 3 and {m.content[:17] for m in act} == {
        f"Decision number {i}" for i in (7, 8, 9)
    }
    summ = await s.list_memories(conn, project_id=project, kind="decision_summary")
    assert len(summ) == 1 and summ[0].topic_key == "decisions.summary"
    everything = await s.list_memories(
        conn, project_id=project, include_inactive=True, kind="decision"
    )
    assert len(everything) == 10  # nothing deleted: archived, not lost
    assert (
        await s.summarize_decisions(conn, llm, project_id=project, user_id="u1", min_items=8)
        is None
    )  # below threshold again


def test_extraction_is_one_topic_per_fact():
    t = {
        f.topic_key: f
        for f in brand_facts(BrandGuideline.model_validate(sd.brand_revised()), "art-1")
    }
    assert set(t) == {
        f"brand.{x}"
        for x in (
            "positioning",
            "personality",
            "messaging",
            "palette",
            "typography",
            "logo",
            "imagery",
            "ui",
        )
    }
    assert (
        "#0B3D2E" in t["brand.palette"].content
        and t["brand.palette"].metadata["artifact_id"] == "art-1"
    )
    a = {f.topic_key for f in architecture_facts(Wireframe.model_validate(sd.wireframe()))}
    assert {"architecture.sitemap", "architecture.navigation", "architecture.ctas"} <= a
