"""Handle-failures node: Manager decision per failed task."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from app.contracts import TaskStatus
from app.contracts.plan import Task
from app.graph.deps import Deps
from app.graph.nodes.common import State, dump_plan, load_plan
from app.graph.state import TaskDecision
from app.store.tasks import audit, set_task_status_by_key

logger = logging.getLogger(__name__)


def make_handle_failures(deps: Deps):
    async def handle_failures(state: State) -> dict[str, Any]:
        """Manager decision per failed task: retry (with the validator's
        complaints as guidance) -> after max attempts ask the user:
        retry / skip.
        """
        plan = load_plan(state)
        pid = state["project_id"]
        new_instr: dict[str, str] = {}
        exhausted: Task | None = None

        for t in plan.tasks:
            if t.status != TaskStatus.FAILED:
                continue
            if t.attempts < deps.max_task_attempts:
                new_instr[t.key] = (
                    f"{t.description}\n"
                    f"Your previous attempt was rejected: {t.error}\n"
                    "Fix these problems; follow the output schema exactly."
                )
                plan.set_status(t.key, TaskStatus.PENDING)
            elif exhausted is None:
                exhausted = t

        if exhausted is not None:
            decision = TaskDecision.model_validate(
                interrupt(
                    {
                        "type": "task_failed",
                        "task_key": exhausted.key,
                        "agent": exhausted.agent.value,
                        "attempts": exhausted.attempts,
                        "error": exhausted.error,
                        "options": ["retry", "skip"],
                    }
                )
            )
            async with deps.conn() as conn:
                await audit(
                    conn,
                    pid,
                    "user",
                    "task_failure_decision",
                    {
                        "task": exhausted.key,
                        "action": decision.action,
                    },
                )
                if decision.action == "skip":
                    plan.set_status(exhausted.key, TaskStatus.SKIPPED, exhausted.error)
                    await set_task_status_by_key(conn, pid, [exhausted.key], "skipped")
                else:
                    plan.set_status(exhausted.key, TaskStatus.PENDING)
                    exhausted.attempts = 0
                    new_instr[exhausted.key] = (
                        f"{exhausted.description}\n" f"Previous errors: {exhausted.error}"
                    )

        return {"plan": dump_plan(plan), "instructions": new_instr}

    return handle_failures
