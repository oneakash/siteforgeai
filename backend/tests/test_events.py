"""Progress events: durable rows, replay-after-id, live tail, and Redis being optional."""

import asyncio
import uuid

import psycopg
import pytest

from app import events
from app.api.events import event_frames
from app.config import DATABASE_URL
from app.store.tasks import audit, set_phase
from tests.graph_env import q

pytestmark = pytest.mark.asyncio
DEAD_REDIS = "redis://127.0.0.1:1/0"  # nothing listens here: simulates Redis being down


async def new_project() -> str:
    pid = str(uuid.uuid4())
    await q(
        "INSERT INTO projects (id, user_id, brand_name, prompt, niche, thread_id) "
        "VALUES (%s,'u1','Aurum','p','Travel',%s) RETURNING id",
        (pid, f"proj-{pid}"),
    )
    return pid


async def never() -> bool:
    return False


def ids(frames):
    return [int(f.split("\n", 1)[0][4:]) for f in frames if f.startswith("id: ")]


async def collect(gen, n, timeout=5.0):
    out = []

    async def run():
        async for f in gen:
            if f.startswith("id: "):
                out.append(f)
                if len(out) == n:
                    return

    await asyncio.wait_for(run(), timeout)
    return out


async def test_set_phase_emits_only_real_transitions():
    pid = await new_project()
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await set_phase(conn, pid, "researching", "running")
        await set_phase(conn, pid, "researching", "running")  # same phase: no new event
        await set_phase(conn, pid, "generating_brand")
        await audit(conn, pid, "manager", "plan_created", {})
        await audit(conn, pid, "manager", "some_internal_detail", {})  # not user-facing
    rows = await q("SELECT type, stage, message FROM run_events WHERE project_id=%s ORDER BY id", (pid,))
    assert [(t, s) for t, s, _ in rows] == [
        ("phase", "researching"),
        ("phase", "generating_brand"),
        ("log", "plan_created"),
    ]


async def test_emit_never_raises_even_with_redis_down(monkeypatch):
    monkeypatch.setattr(events, "REDIS_URL", DEAD_REDIS)
    monkeypatch.setattr(events, "_client", None)
    monkeypatch.setattr(events, "_down_until", 0.0)
    pid = await new_project()
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        eid = await events.emit(conn, pid, "log", "hello")
    assert eid is not None  # the durable row is written even though the ping failed


async def test_stream_replays_after_id_then_tails_live_without_redis():
    pid = await new_project()
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        a = await events.emit(conn, pid, "log", "one")
        b = await events.emit(conn, pid, "log", "two")
        c = await events.emit(conn, pid, "log", "three")

    # reconnect with Last-Event-ID = a  ->  only b and c are replayed
    gen = event_frames(pid, a, is_disconnected=never, redis_url=DEAD_REDIS, poll_s=0.1)
    assert ids(await collect(gen, 2)) == [b, c]
    await gen.aclose()

    # live tail: an event written AFTER the stream opened still arrives (polling fallback)
    gen = event_frames(pid, c, is_disconnected=never, redis_url=DEAD_REDIS, poll_s=0.1)

    async def later():
        await asyncio.sleep(0.3)
        async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
            return await events.emit(conn, pid, "log", "four")

    task = asyncio.create_task(later())
    got = await collect(gen, 1)
    await gen.aclose()
    assert ids(got) == [await task]


async def test_stream_is_isolated_per_project():
    p1, p2 = await new_project(), await new_project()
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await events.emit(conn, p1, "log", "mine")
        await events.emit(conn, p2, "log", "not mine")
    gen = event_frames(p1, 0, is_disconnected=never, redis_url=DEAD_REDIS, poll_s=0.1)
    frames = await collect(gen, 1)
    await gen.aclose()
    assert "mine" in frames[0] and "not mine" not in frames[0]
