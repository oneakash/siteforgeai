"""Collect node: Manager evaluates worker results and updates the plan."""

from __future__ import annotations

import logging
from typing import Any

from app.contracts import TaskStatus
from app.graph.deps import Deps
from app.graph.nodes.common import State, dump_plan, load_plan
from app.store.tasks import audit

logger = logging.getLogger(__name__)


def make_collect(deps: Deps):
    async def collect(state: State) -> dict[str, Any]:
        logger.info("📊 [COLLECT] Evaluating worker results...")
        plan = load_plan(state)
        results = state.get("task_results", {})

        async with deps.conn() as conn:
            for t in plan.tasks:
                r = results.get(t.key)
                if not r or t.status in (
                    TaskStatus.SUPERSEDED,
                    TaskStatus.SKIPPED,
                    TaskStatus.COMPLETED,
                ):
                    continue
                if r["attempts"] <= t.attempts:
                    continue  # stale result from an earlier round
                t.attempts = r["attempts"]
                if r["status"] == "completed":
                    plan.set_status(t.key, TaskStatus.COMPLETED)
                else:
                    plan.set_status(t.key, TaskStatus.FAILED, r.get("error"))
            await audit(
                conn,
                state["project_id"],
                "manager",
                "results_collected",
                {t.key: t.status.value for t in plan.tasks},
            )
        return {"plan": dump_plan(plan)}

    return collect
