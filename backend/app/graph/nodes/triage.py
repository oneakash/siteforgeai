"""Triage + clarify nodes for the brand-feedback loop."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from app.agents.registry import AGENTS
from app.agents.runner import run_agent
from app.contracts import BrandFeedbackTriage, BrandGuideline, TaskStatus
from app.graph.deps import Deps
from app.graph.nodes.common import State, dump_plan, load_plan, session_of
from app.graph.nodes.memory import recall_for, remember_safely
from app.graph.state import ClarificationAnswer
from app.store.artifacts import load_latest, save_artifact
from app.store.tasks import audit, ensure_tasks, set_task_status_by_key

logger = logging.getLogger(__name__)


def make_triage_feedback(deps: Deps):
    async def triage_feedback(state: State) -> dict[str, Any]:
        """Manager turns free-text feedback into the SMALLEST set of
        agents to re-run.
        """
        pid = state["project_id"]
        plan = load_plan(state)
        feedback = state["brand_feedback"]

        async with deps.conn() as conn:
            brand = await load_latest(conn, pid, "brand_guideline")
            bg: BrandGuideline = brand.content  # type: ignore[assignment]
            summary = {
                "palette": bg.palette.model_dump(),
                "typography": bg.typography.model_dump(),
                "tone": bg.personality.tone_of_voice,
                "positioning": bg.positioning.statement,
            }
            force = state.get("clarify_rounds", 0) >= 2

            mems = await recall_for(
                conn,
                deps,
                pid=pid,
                uid=state["user_id"],
                agent="manager.triage_brand_feedback",
                query=feedback,
            )
            res = await run_agent(
                AGENTS["manager.triage_brand_feedback"],
                llm=deps.llm,
                project_id=pid,
                memories=mems,
                inputs={
                    "feedback": feedback,
                    "current_brand_summary": summary,
                    "agents_in_plan": [
                        t.agent.value for t in plan.tasks if t.status != TaskStatus.SUPERSEDED
                    ],
                },
                instruction="Decide which agents must re-run."
                + (" Do NOT ask further questions; decide now." if force else ""),
            )
            tri: BrandFeedbackTriage = res.output  # type: ignore[assignment]

            if tri.clarifying_question and tri.confidence < 0.6 and not force:
                await audit(
                    conn,
                    pid,
                    "manager",
                    "clarification_requested",
                    {"question": tri.clarifying_question},
                )
                return {"clarification": tri.clarifying_question}

            keys: set[str] = set()
            per_key: dict[str, str] = {}
            for ag in tri.affected_agents:
                t = plan.active_task(ag.value)
                if t:
                    keys.add(t.key)
                    per_key[t.key] = tri.instructions.get(ag.value, feedback)
            if not keys:
                # Triage named nothing we have: default to the brand task.
                t = plan.active_task("brand_guideline")
                keys.add(t.key)  # type: ignore[union-attr]
                per_key[t.key] = feedback  # type: ignore[union-attr]

            mapping = plan.rerun(keys)
            instr: dict[str, str] = {}
            for old in set(keys) | set(mapping):
                new = mapping.get(old, old)
                msg = per_key.get(
                    old,
                    "Upstream inputs changed; stay consistent with the " "updated artifacts.",
                )
                instr[new] = f"User feedback: {feedback}\nChange requested: {msg}"

            task_ids = await ensure_tasks(conn, pid, plan.tasks)
            await set_task_status_by_key(conn, pid, mapping.keys(), "superseded")
            await save_artifact(conn, project_id=pid, kind="execution_plan", content=plan)
            await audit(
                conn,
                pid,
                "manager",
                "feedback_triaged",
                {
                    "affected": [a.value for a in tri.affected_agents],
                    "rerun": mapping,
                    "plan_version": plan.version,
                },
            )

            if deps.memory:
                # The user's decision becomes long-term memory
                # (deduped; old ones get summarized).
                short = " ".join(feedback.split())[:400]
                await remember_safely(
                    conn,
                    deps,
                    pid,
                    "decision",
                    deps.memory.log_decision(
                        conn,
                        user_id=state["user_id"],
                        project_id=pid,
                        text=(
                            "User feedback on brand guideline revision "
                            f'{bg.revision}: "{short}". '
                            "Manager re-ran: "
                            f'{", ".join(sorted(a.value for a in tri.affected_agents))}.'
                        ),
                        metadata={"revision": bg.revision},
                    ),
                )
                try:
                    await deps.memory.summarize_decisions(
                        conn,
                        deps.llm,
                        project_id=pid,
                        user_id=state["user_id"],
                    )
                except Exception as e:  # noqa: BLE001
                    await audit(
                        conn,
                        pid,
                        "system",
                        "memory_error",
                        {"op": "summarize", "error": str(e)[:300]},
                    )

        return {
            "plan": dump_plan(plan),
            "task_ids": task_ids,
            "instructions": instr,
            "clarification": None,
            "brand_approved": False,
            "phase": "generating_brand",
        }

    return triage_feedback


def make_clarify(deps: Deps):
    async def clarify(state: State) -> dict[str, Any]:
        ans = ClarificationAnswer.model_validate(
            interrupt(
                {
                    "type": "clarification",
                    "question": state["clarification"],
                }
            )
        )
        async with deps.conn() as conn:
            await audit(
                conn,
                state["project_id"],
                "user",
                "clarification_answer",
                {"answer": ans.answer},
            )
            if deps.memory:
                # SESSION-scope: useful context for this conversation only.
                await remember_safely(
                    conn,
                    deps,
                    state["project_id"],
                    "session_note",
                    deps.memory.remember(
                        conn,
                        scope="session",
                        user_id=state["user_id"],
                        project_id=state["project_id"],
                        session_id=session_of(state["project_id"]),
                        kind="clarification",
                        content=(f"Q: {state['clarification']} A: {ans.answer}"),
                    ),
                )
        return {
            "brand_feedback": (f"{state['brand_feedback']}\n" f"Clarification: {ans.answer}"),
            "clarify_rounds": state.get("clarify_rounds", 0) + 1,
            "clarification": None,
        }

    return clarify
