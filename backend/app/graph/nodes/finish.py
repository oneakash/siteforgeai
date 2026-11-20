"""Finish node: mark the stage as finished."""

from __future__ import annotations

import logging
from typing import Any

from app.contracts import TaskStatus
from app.graph.deps import Deps
from app.graph.nodes.common import State, load_plan
from app.store.tasks import audit, set_phase

logger = logging.getLogger(__name__)


def make_finish(deps: Deps):
    async def finish(state: State) -> dict[str, Any]:
        plan = load_plan(state)
        pending = [t for t in plan.tasks if t.status == TaskStatus.PENDING]

        if state.get("site_document_id"):
            phase = "published"
        elif pending:
            phase = "build_pending"
        else:
            phase = "wireframe_complete"

        async with deps.conn() as conn:
            await set_phase(
                conn,
                state["project_id"],
                phase,
                "paused" if pending else "idle",
            )
            await audit(
                conn,
                state["project_id"],
                "manager",
                "stage_finished",
                {"phase": phase, "pending": [t.key for t in pending]},
            )
        return {"phase": phase}

    return finish
