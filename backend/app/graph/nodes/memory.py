"""Memory helpers.

Memory failures must never break the workflow, so every public
function here swallows exceptions and audits them instead.
"""

from __future__ import annotations

import logging
from typing import Any

from app.graph.deps import Deps
from app.graph.nodes.common import session_of
from app.store.tasks import audit

logger = logging.getLogger(__name__)


async def recall_for(
    conn: Any,
    deps: Deps,
    *,
    pid: str,
    uid: str,
    agent: str,
    query: str,
) -> list[tuple[str, str]]:
    """Return agent-specific memory context, or an empty list on failure."""
    if not deps.memory:
        return []
    try:
        mems = await deps.memory.for_agent(
            conn,
            project_id=pid,
            user_id=uid,
            agent=agent,
            query=query,
            session_id=session_of(pid),
        )
        if mems:
            await audit(
                conn,
                pid,
                "manager",
                "memory_recalled",
                {
                    "agent": agent,
                    "topics": [m.topic_key or m.kind for m in mems],
                    "ids": [str(m.id) for m in mems],
                },
            )
        return deps.memory.to_prompt(mems)
    except Exception as e:
        await audit(
            conn,
            pid,
            "system",
            "memory_error",
            {"op": "recall", "agent": agent, "error": str(e)[:300]},
        )
        return []


async def remember_safely(
    conn: Any,
    deps: Deps,
    pid: str,
    what: str,
    coro: Any,
) -> None:
    """Await a memory-write coroutine and audit the outcome, never raising."""
    if not deps.memory:
        return
    try:
        results = await coro
        results = results if isinstance(results, list) else [results]
        await audit(
            conn,
            pid,
            "manager",
            "memory_written",
            {
                "what": what,
                **{
                    st: sum(1 for r in results if r and r.status == st)
                    for st in ("created", "superseded", "duplicate")
                },
                "without_embedding": sum(1 for r in results if r and not r.embedded),
            },
        )
    except Exception as e:
        await audit(
            conn,
            pid,
            "system",
            "memory_error",
            {"op": what, "error": str(e)[:300]},
        )
