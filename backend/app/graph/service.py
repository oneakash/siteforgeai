"""Thin service layer over the compiled graph (FastAPI will call these in Step 7)."""

import logging
import uuid
from typing import Any

import psycopg
from langgraph.types import Command

from app.agents.errors import TransientAgentError
from app.graph.deps import Deps
from app.graph.state import ClarificationAnswer, ReviewDecision, TaskDecision
from app.store.tasks import audit

logger = logging.getLogger(__name__)

INTERRUPT_MODELS = {
    "brand_review": ReviewDecision,
    "clarification": ClarificationAnswer,
    "task_failed": TaskDecision,
}
CONFIG_EXTRA = {"recursion_limit": 100}


def _cfg(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}, **CONFIG_EXTRA}


async def _thread_for(deps: Deps, project_id: str) -> str:
    async with await psycopg.AsyncConnection.connect(deps.dsn) as conn:
        row = await (
            await conn.execute("SELECT thread_id FROM projects WHERE id=%s::uuid", (project_id,))
        ).fetchone()
    if not row:
        raise KeyError(f"unknown project {project_id}")
    return row[0]


async def _run(graph, deps: Deps, project_id: str, graph_input: Any) -> dict:
    thread = await _thread_for(deps, project_id)
    logger.info(f"▶️  [GRAPH] Invoking workflow for project {project_id} (Thread: {thread})")
    try:
        # durability="sync": every super-step's checkpoint is committed before the next begins.
        await graph.ainvoke(graph_input, _cfg(thread), durability="sync")
        logger.info(f"🏁 [GRAPH] Workflow finished for project {project_id}.")
    except TransientAgentError as e:  # retries exhausted: leave state resumable; operator may switch model then continue_run()
        logger.error(f"❌ [GRAPH] Workflow failed (Transient): {e}")
        async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
            await audit(
                conn,
                project_id,
                "system",
                "workflow_error",
                {"error": str(e)[:500], "retryable": True},
            )
        return {**await status(graph, deps, project_id), "error": str(e)[:500]}
    return await status(graph, deps, project_id)


async def pending_resume_token(graph, deps: Deps, project_id: str) -> str | None:
    """Identifies the interrupt the workflow is waiting on (its checkpoint id), or None.

    The API captures this when it enqueues a resume; the worker refuses to apply an answer to
    a DIFFERENT interrupt (e.g. a double-clicked "approve" landing on the next review).
    """
    snap = await graph.aget_state(_cfg(await _thread_for(deps, project_id)))
    if not any(t.interrupts for t in snap.tasks):
        return None
    return snap.config["configurable"]["checkpoint_id"]


async def _start_input(deps: Deps, project_id: str) -> dict:
    async with await psycopg.AsyncConnection.connect(deps.dsn) as conn:
        row = await (
            await conn.execute(
                "SELECT user_id, brand_name, prompt, niche FROM projects WHERE id=%s::uuid",
                (project_id,),
            )
        ).fetchone()
    if not row:
        raise KeyError(f"unknown project {project_id}")
    return {
        "project_id": project_id,
        "user_id": row[0],
        "brand_name": row[1],
        "prompt": row[2],
        "niche": row[3],
        "brand_approved": False,
    }


async def run_job(
    graph,
    deps: Deps,
    project_id: str,
    *,
    mode: str,
    payload: dict | None = None,
    token: str | None = None,
) -> dict:
    """Idempotent entry point for a queued run (safe to execute twice).

    Decides what to do from the CURRENT checkpoint, not from what the message says happened:
      * no checkpoint yet            -> start from the project row
      * waiting on an interrupt      -> apply the resume payload (if it targets THIS interrupt)
      * mid-run (crash / redelivery) -> continue from the last checkpoint
      * finished, or waiting for the user -> no-op
    """
    thread = await _thread_for(deps, project_id)
    snap = await graph.aget_state(_cfg(thread))
    waiting = next((t.interrupts[0] for t in snap.tasks if t.interrupts), None)
    started = bool(snap.values)

    if mode == "resume":
        if not started:
            raise ValueError("cannot resume a project that has not started")
        if waiting is not None:
            current = snap.config["configurable"].get("checkpoint_id")
            if token is not None and token != current:
                logger.warning(f"⚠️  [JOB] stale resume for {project_id} dropped")
                async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as c:
                    await audit(c, project_id, "system", "stale_resume_dropped", {})
                return await status(graph, deps, project_id)
            INTERRUPT_MODELS[waiting.value["type"]].model_validate(payload or {})
            return await _run(graph, deps, project_id, Command(resume=payload))
        # not waiting: an earlier delivery already applied it; fall through to "continue"

    if not started:
        return await _run(graph, deps, project_id, await _start_input(deps, project_id))
    if waiting is not None or not snap.next:
        return await status(graph, deps, project_id)  # waiting for the user, or finished
    return await _run(graph, deps, project_id, None)


async def start_project(
    graph, deps: Deps, *, user_id: str, brand_name: str, prompt: str, niche: str
) -> dict:
    logger.info(f"🆕 [PROJECT] Starting new project (brand: {brand_name}, niche: {niche})")
    pid = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO projects (id, user_id, brand_name, prompt, niche, thread_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (pid, user_id, brand_name, prompt, niche, f"proj-{pid}"),
        )
        await audit(
            conn, pid, "user", "project_created", {"brand_name": brand_name, "niche": niche}
        )
    out = await _run(
        graph,
        deps,
        pid,
        {
            "project_id": pid,
            "user_id": user_id,
            "brand_name": brand_name,
            "prompt": prompt,
            "niche": niche,
            "brand_approved": False,
        },
    )
    return {"project_id": pid, **out}


async def resume(graph, deps: Deps, project_id: str, payload: dict) -> dict:
    """Answer the pending interrupt. Payload is validated BEFORE touching the graph."""
    logger.info(f"🔄 [GRAPH] Resuming workflow for project {project_id} with payload: {payload}")
    st = await status(graph, deps, project_id)
    wait = st["waiting_for"]
    if not wait:
        raise ValueError("workflow is not waiting for input")
    INTERRUPT_MODELS[wait["type"]].model_validate(payload)
    return await _run(graph, deps, project_id, Command(resume=payload))


async def continue_run(graph, deps: Deps, project_id: str) -> dict:
    """Recover after a crash / restart / exhausted retries: continue from the last checkpoint."""
    logger.info(f"♻️  [GRAPH] Continuing workflow for project {project_id} from last checkpoint")
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
    async with await psycopg.AsyncConnection.connect(
        deps.dsn
    ) as conn:  # projects.phase is the live UI phase
        row = await (
            await conn.execute("SELECT phase FROM projects WHERE id=%s::uuid", (project_id,))
        ).fetchone()
    return {
        "phase": row[0],
        "waiting_for": waiting,
        "next": list(snap.next),
        "tasks": [
            {"key": t["key"], "agent": t["agent"], "status": t["status"], "attempts": t["attempts"]}
            for t in (plan or {}).get("tasks", [])
        ],
        "plan_version": (plan or {}).get("version"),
    }
