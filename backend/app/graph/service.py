"""Thin service layer over the compiled graph (FastAPI will call these in Step 7)."""
import uuid
from typing import Any

import psycopg
from langgraph.types import Command

from app.agents.errors import TransientAgentError
from app.graph.deps import Deps
from app.graph.state import ClarificationAnswer, ReviewDecision, TaskDecision
from app.store.tasks import audit

INTERRUPT_MODELS = {"brand_review": ReviewDecision, "clarification": ClarificationAnswer, "task_failed": TaskDecision}
CONFIG_EXTRA = {"recursion_limit": 100}


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, **CONFIG_EXTRA}


async def _thread_for(deps: Deps, project_id: str) -> str:
    async with await psycopg.AsyncConnection.connect(deps.dsn) as conn:
        row = await (await conn.execute("SELECT thread_id FROM projects WHERE id=%s::uuid", (project_id,))).fetchone()
    if not row:
        raise KeyError(f"unknown project {project_id}")
    return row[0]


async def _run(graph, deps: Deps, project_id: str, graph_input: Any) -> dict:
    thread = await _thread_for(deps, project_id)
    try:
        # durability="sync": every super-step's checkpoint is committed before the next begins.
        await graph.ainvoke(graph_input, _cfg(thread), durability="sync")
    except TransientAgentError as e:  # retries exhausted: leave state resumable; operator may switch model then continue_run()
        async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
            await audit(conn, project_id, "system", "workflow_error", {"error": str(e)[:500], "retryable": True})
        return {**await status(graph, deps, project_id), "error": str(e)[:500]}
    return await status(graph, deps, project_id)


async def start_project(graph, deps: Deps, *, user_id: str, brand_name: str, prompt: str, niche: str) -> dict:
    pid = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO projects (id, user_id, brand_name, prompt, niche, thread_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (pid, user_id, brand_name, prompt, niche, f"proj-{pid}"),
        )
        await audit(conn, pid, "user", "project_created", {"brand_name": brand_name, "niche": niche})
    out = await _run(graph, deps, pid, {"project_id": pid, "user_id": user_id, "brand_name": brand_name,
                                        "prompt": prompt, "niche": niche, "brand_approved": False})
    return {"project_id": pid, **out}


async def resume(graph, deps: Deps, project_id: str, payload: dict) -> dict:
    """Answer the pending interrupt. Payload is validated BEFORE touching the graph."""
    st = await status(graph, deps, project_id)
    wait = st["waiting_for"]
    if not wait:
        raise ValueError("workflow is not waiting for input")
    INTERRUPT_MODELS[wait["type"]].model_validate(payload)
    return await _run(graph, deps, project_id, Command(resume=payload))


async def continue_run(graph, deps: Deps, project_id: str) -> dict:
    """Recover after a crash / restart / exhausted retries: continue from the last checkpoint."""
    return await _run(graph, deps, project_id, None)


async def status(graph, deps: Deps, project_id: str) -> dict:
    thread = await _thread_for(deps, project_id)
    snap = await graph.aget_state(_cfg(thread))
    waiting = None
    for t in snap.tasks:
        if t.interrupts:
            waiting = t.interrupts[0].value
            break
    plan = (snap.values or {}).get("plan")
    async with await psycopg.AsyncConnection.connect(deps.dsn) as conn:  # projects.phase is the live UI phase
        row = await (await conn.execute("SELECT phase FROM projects WHERE id=%s::uuid", (project_id,))).fetchone()
    return {
        "phase": row[0],
        "waiting_for": waiting,
        "next": list(snap.next),
        "tasks": [{"key": t["key"], "agent": t["agent"], "status": t["status"], "attempts": t["attempts"]}
                  for t in (plan or {}).get("tasks", [])],
        "plan_version": (plan or {}).get("version"),
    }
