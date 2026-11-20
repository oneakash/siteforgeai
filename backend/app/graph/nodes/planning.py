"""Plan-creation node."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.execute import execute_task
from app.agents.registry import AGENTS
from app.contracts import ExecutionPlan
from app.contracts.plan import AgentName, Task
from app.graph.deps import Deps
from app.graph.nodes.common import State, dump_plan
from app.graph.nodes.memory import recall_for
from app.store.tasks import audit, claim_task, ensure_tasks, finish_task, set_phase

logger = logging.getLogger(__name__)


def make_plan_node(deps: Deps):
    async def plan_node(state: State) -> dict[str, Any]:
        if state.get("plan"):
            return {}
        pid = state["project_id"]
        logger.info(f"🧠 [PLAN] Starting planning for project {pid}")

        async with deps.conn() as conn:
            await set_phase(conn, pid, "planning", "running")
            plan_task = Task(
                key="plan",
                agent=AgentName.MANAGER,
                description="Create the execution plan",
            )
            tid = (await ensure_tasks(conn, pid, [plan_task]))["plan"]
            await claim_task(conn, tid)

            mems = await recall_for(
                conn,
                deps,
                pid=pid,
                uid=state["user_id"],
                agent="manager.plan",
                query=(f"{state['brand_name']} {state['niche']} {state['prompt']}"),
            )
            ex = await execute_task(
                conn,
                project_id=pid,
                task_id=tid,
                spec=AGENTS["manager.plan"],
                llm=deps.llm,
                memories=mems,
                inputs={
                    "brand_name": state["brand_name"],
                    "niche": state["niche"],
                    "prompt": state["prompt"],
                },
                instruction="Create the execution plan for this website project.",
                to_artifact=lambda d: ExecutionPlan.from_draft(d),
                kind="execution_plan",
            )
            await finish_task(conn, tid, "completed")

            plan: ExecutionPlan = ex.artifact.content  # type: ignore[assignment]
            task_ids = await ensure_tasks(conn, pid, plan.tasks)
            await audit(
                conn,
                pid,
                "manager",
                "plan_created",
                {
                    "tasks": [(t.key, t.agent.value, t.depends_on) for t in plan.tasks],
                    "batches": plan.batches(),
                },
            )
            await set_phase(conn, pid, "researching")

        logger.info(f"✅ [PLAN] Plan created with {len(plan.tasks)} tasks.")
        return {
            "plan": dump_plan(plan),
            "task_ids": task_ids,
            "phase": "researching",
        }

    return plan_node
