"""Worker node: execute a single agent task."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from app.agents.errors import AgentOutputError
from app.agents.execute import execute_task
from app.agents.registry import AGENTS
from app.graph.deps import Deps
from app.graph.inputs import build_inputs
from app.graph.nodes.common import PHASE_FOR_AGENT
from app.graph.nodes.memory import recall_for
from app.store.artifacts import load_for_task
from app.store.tasks import audit, claim_task, finish_task, set_phase, task_attempts

logger = logging.getLogger(__name__)


def _bump_revision(base_rev: int) -> Callable[[Any], Any]:
    """Return a transformer that stamps a new revision on a brand guideline."""

    def bump(out: Any) -> Any:
        return out.model_copy(update={"revision": base_rev})

    return bump


def make_worker(deps: Deps):
    async def worker(p: dict[str, Any]) -> dict[str, Any]:
        """One agent task.

        Used inside the research subgraph AND at the root. TransientAgentError
        propagates on purpose: LangGraph's RetryPolicy retries this node.
        """
        key, tid, agent = p["task_key"], p["task_id"], p["agent"]
        pid = p["project_id"]
        spec = AGENTS[agent]
        logger.info(f"⚙️  [WORKER] Starting task '{key}' (Agent: {agent})")

        async with deps.conn() as conn:
            attempt = await claim_task(conn, tid)
            if attempt is None:
                # Ledger says completed => never execute twice (recovery path).
                logger.info(f"⏭️  [WORKER] Task '{key}' already completed (skipping).")
                art = await load_for_task(conn, tid)
                return {
                    "artifact_ids": {art.kind: str(art.id)} if art else {},
                    "task_results": {
                        key: {
                            "status": "completed",
                            "attempts": await task_attempts(conn, tid),
                        }
                    },
                }

            await set_phase(conn, pid, PHASE_FOR_AGENT.get(agent, "researching"))

            try:
                inputs = await build_inputs(
                    conn,
                    project_id=pid,
                    agent=agent,
                    brand_name=p["brand_name"],
                    niche=p["niche"],
                    prompt=p["prompt"],
                    revision=bool(p.get("is_revision")),
                    task_key=key,
                )
                to_art: Callable[[Any], Any] | None = None
                if agent == "brand_guideline":
                    prev = inputs.get("previous_brand_guideline")
                    if prev:
                        to_art = _bump_revision(prev.revision + 1)

                mems = await recall_for(
                    conn,
                    deps,
                    pid=pid,
                    uid=p["user_id"],
                    agent=agent,
                    query=f"{p['niche']} {p.get('instruction', '')}",
                )
                ex = await execute_task(
                    conn,
                    project_id=pid,
                    task_id=tid,
                    spec=spec,
                    llm=deps.llm,
                    inputs=inputs,
                    memories=mems,
                    instruction=p.get("instruction", ""),
                    to_artifact=to_art,
                )
            except AgentOutputError as e:
                # The model could not produce valid output: Manager decides.
                logger.warning(f"⚠️  [WORKER] Task '{key}' failed validation: {e}")
                await finish_task(conn, tid, "failed", str(e)[:1000])
                await audit(
                    conn,
                    pid,
                    agent,
                    "task_failed",
                    {
                        "task": key,
                        "attempt": attempt,
                        "error": str(e)[:500],
                    },
                )
                return {
                    "task_results": {
                        key: {
                            "status": "failed",
                            "error": str(e)[:1000],
                            "attempts": attempt,
                        }
                    }
                }

            await finish_task(conn, tid, "completed")
            logger.info(f"✅ [WORKER] Task '{key}' completed successfully.")
            return {
                "artifact_ids": {ex.artifact.kind: str(ex.artifact.id)},
                "task_results": {
                    key: {
                        "status": "completed",
                        "attempts": attempt,
                        "model": ex.model,
                    }
                },
            }

    return worker
