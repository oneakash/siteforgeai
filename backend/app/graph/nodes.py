"""Graph nodes. Rules every node follows:
  * idempotent: safe to re-run after a crash or an interrupt resume
  * side effects go through the ledger / artifact store (unique keys)
  * state carries ids and small control data, never bulky artifacts
"""
from typing import Any

from langgraph.types import interrupt

from app.agents.errors import AgentOutputError
from app.agents.execute import execute_task
from app.agents.registry import AGENTS
from app.agents.runner import run_agent
from app.contracts import (AudienceReport, BrandFeedbackTriage, BrandGuideline, CompetitorReport, ExecutionPlan,
                           NicheReport, ResearchDigest, SEOStrategy, TaskStatus)
from app.contracts.plan import AgentName, Task
from app.graph.deps import Deps
from app.graph.inputs import RESEARCH_AGENTS, RESEARCH_KINDS, build_inputs
from app.graph.state import ClarificationAnswer, ReviewDecision, TaskDecision
from app.store.artifacts import approve_artifact, load_for_task, load_latest, save_artifact
from app.store.tasks import (audit, claim_task, ensure_tasks, finish_task, set_phase, set_task_status_by_key,
                             task_attempts)

def session_of(project_id: str) -> str:
    return f"proj-{project_id}"   # == the LangGraph thread_id (see service.start_project)


async def recall_for(conn, deps: Deps, *, pid: str, uid: str, agent: str, query: str) -> list[tuple[str, str]]:
    """Agent-specific memory context. Memory trouble must never break the workflow."""
    if not deps.memory:
        return []
    try:
        mems = await deps.memory.for_agent(conn, project_id=pid, user_id=uid, agent=agent, query=query, session_id=session_of(pid))
        if mems:
            await audit(conn, pid, "manager", "memory_recalled",
                        {"agent": agent, "topics": [m.topic_key or m.kind for m in mems], "ids": [str(m.id) for m in mems]})
        return deps.memory.to_prompt(mems)
    except Exception as e:  # noqa: BLE001
        await audit(conn, pid, "system", "memory_error", {"op": "recall", "agent": agent, "error": str(e)[:300]})
        return []


async def remember_safely(conn, deps: Deps, pid: str, what: str, coro) -> None:
    if not deps.memory:
        return
    try:
        results = await coro
        results = results if isinstance(results, list) else [results]
        await audit(conn, pid, "manager", "memory_written",
                    {"what": what, **{st: sum(1 for r in results if r and r.status == st) for st in ("created", "superseded", "duplicate")},
                     "without_embedding": sum(1 for r in results if r and not r.embedded)})
    except Exception as e:  # noqa: BLE001
        await audit(conn, pid, "system", "memory_error", {"op": what, "error": str(e)[:300]})


PHASE_FOR_AGENT = {"brand_guideline": "generating_brand", "wireframe": "wireframing"}


def load_plan(state) -> ExecutionPlan:
    return ExecutionPlan.model_validate(state["plan"])


def dump_plan(plan: ExecutionPlan) -> dict:
    return plan.model_dump(mode="json")


def build_digest(arts: dict[str, Any], ids: dict[str, str]) -> ResearchDigest:
    n: NicheReport | None = arts.get("niche_report")
    a: AudienceReport | None = arts.get("audience_report")
    c: CompetitorReport | None = arts.get("competitor_report")
    s: SEOStrategy | None = arts.get("seo_strategy")
    return ResearchDigest(
        niche=n.niche if n else "", business_model=n.business_model if n else "",
        top_trends=[t.trend for t in n.market_trends[:4]] if n else [],
        needs=list(a.customer_needs[:5]) if a else [],
        personas=[f"{p.name}: {p.goals[0]}" for p in a.personas] if a else [],
        competitors=[x.name for x in c.competitors] if c else [],
        differentiators=list(c.differentiation_opportunities[:4]) if c else [],
        primary_keywords=[k.term for k in s.primary_keywords] if s else [],
        recommended_pages=[p.slug for p in s.recommended_pages] if s else [],
        source_artifact_ids=ids,
    )


def make_nodes(deps: Deps):
    # ------------------------------------------------------------------ plan
    async def plan_node(state):
        if state.get("plan"):
            return {}
        pid = state["project_id"]
        async with deps.conn() as conn:
            await set_phase(conn, pid, "planning", "running")
            plan_task = Task(key="plan", agent=AgentName.MANAGER, description="Create the execution plan")
            tid = (await ensure_tasks(conn, pid, [plan_task]))["plan"]
            await claim_task(conn, tid)
            mems = await recall_for(conn, deps, pid=pid, uid=state["user_id"], agent="manager.plan",
                                    query=f"{state['brand_name']} {state['niche']} {state['prompt']}")
            ex = await execute_task(
                conn, project_id=pid, task_id=tid, spec=AGENTS["manager.plan"], llm=deps.llm, memories=mems,
                inputs={"brand_name": state["brand_name"], "niche": state["niche"], "prompt": state["prompt"]},
                instruction="Create the execution plan for this website project.",
                to_artifact=lambda d: ExecutionPlan.from_draft(d), kind="execution_plan",
            )
            await finish_task(conn, tid, "completed")
            plan: ExecutionPlan = ex.artifact.content  # type: ignore[assignment]
            task_ids = await ensure_tasks(conn, pid, plan.tasks)
            await audit(conn, pid, "manager", "plan_created",
                        {"tasks": [(t.key, t.agent.value, t.depends_on) for t in plan.tasks], "batches": plan.batches()})
            await set_phase(conn, pid, "researching")
        return {"plan": dump_plan(plan), "task_ids": task_ids, "phase": "researching"}

    # ---------------------------------------------------------------- worker
    async def worker(p):
        """One agent task. Used inside the research subgraph AND at the root."""
        key, tid, agent = p["task_key"], p["task_id"], p["agent"]
        pid = p["project_id"]
        spec = AGENTS[agent]
        async with deps.conn() as conn:
            attempt = await claim_task(conn, tid)
            if attempt is None:  # ledger says completed => never execute twice (recovery path)
                art = await load_for_task(conn, tid)
                return {"artifact_ids": {art.kind: str(art.id)} if art else {},
                        "task_results": {key: {"status": "completed", "attempts": await task_attempts(conn, tid)}}}
            await set_phase(conn, pid, PHASE_FOR_AGENT.get(agent, "researching"))
            try:
                inputs = await build_inputs(conn, project_id=pid, agent=agent, brand_name=p["brand_name"],
                                            niche=p["niche"], prompt=p["prompt"], revision=bool(p.get("is_revision")))
                to_art = None
                if agent == "brand_guideline":
                    prev = inputs.get("previous_brand_guideline")
                    if prev:
                        to_art = lambda out, r=prev.revision + 1: out.model_copy(update={"revision": r})  # noqa: E731
                mems = await recall_for(conn, deps, pid=pid, uid=p["user_id"], agent=agent,
                                        query=f"{p['niche']} {p.get('instruction', '')}")
                ex = await execute_task(conn, project_id=pid, task_id=tid, spec=spec, llm=deps.llm, inputs=inputs,
                                        memories=mems, instruction=p.get("instruction", ""), to_artifact=to_art)
            except AgentOutputError as e:  # model could not produce valid output: Manager decides what next
                await finish_task(conn, tid, "failed", str(e)[:1000])
                await audit(conn, pid, agent, "task_failed", {"task": key, "attempt": attempt, "error": str(e)[:500]})
                return {"task_results": {key: {"status": "failed", "error": str(e)[:1000], "attempts": attempt}}}
            # TransientAgentError propagates on purpose: LangGraph RetryPolicy retries this node.
            await finish_task(conn, tid, "completed")
            return {"artifact_ids": {ex.artifact.kind: str(ex.artifact.id)},
                    "task_results": {key: {"status": "completed", "attempts": attempt, "model": ex.model}}}

    # ---------------------------------------------------------------- collect
    async def collect(state):
        """Manager evaluates worker results and updates the plan."""
        plan = load_plan(state)
        results = state.get("task_results", {})
        async with deps.conn() as conn:
            for t in plan.tasks:
                r = results.get(t.key)
                if not r or t.status in (TaskStatus.SUPERSEDED, TaskStatus.SKIPPED, TaskStatus.COMPLETED):
                    continue
                if r["attempts"] <= t.attempts:   # stale result from an earlier round
                    continue
                t.attempts = r["attempts"]
                if r["status"] == "completed":
                    plan.set_status(t.key, TaskStatus.COMPLETED)
                else:
                    plan.set_status(t.key, TaskStatus.FAILED, r.get("error"))
            await audit(conn, state["project_id"], "manager", "results_collected",
                        {t.key: t.status.value for t in plan.tasks})
        return {"plan": dump_plan(plan)}

    # ------------------------------------------------------------ consolidate
    async def consolidate(state):
        pid = state["project_id"]
        ids = state.get("artifact_ids", {})
        async with deps.conn() as conn:
            arts = {}
            for kind in RESEARCH_KINDS:
                a = await load_latest(conn, pid, kind)
                if a:
                    arts[kind] = a.content
            src = {k: ids[k] for k in RESEARCH_KINDS if k in ids}
            prev = await load_latest(conn, pid, "research_digest")
            if not (prev and prev.content.source_artifact_ids == src):   # replay-safe
                stored = await save_artifact(conn, project_id=pid, kind="research_digest", content=build_digest(arts, src))
                await audit(conn, pid, "manager", "research_consolidated", {"digest_version": stored.version, "sources": src})
                ids = {**ids, "research_digest": str(stored.id)}
            await remember_safely(conn, deps, pid, "research", deps.memory.write_research(
                conn, user_id=state["user_id"], project_id=pid, niche=arts.get("niche_report"),
                audience=arts.get("audience_report"), competitors=arts.get("competitor_report"),
                seo=arts.get("seo_strategy")) if deps.memory else None)
        key = "|".join(state.get("artifact_ids", {}).get(k, "") for k in RESEARCH_KINDS)
        return {"digest_for": key, "artifact_ids": {"research_digest": ids.get("research_digest", "")}}

    # -------------------------------------------------------- failure handling
    async def handle_failures(state):
        """Manager decision per failed task: retry (with the validator's complaints
        as guidance) -> after max attempts ask the user: retry / skip."""
        plan = load_plan(state)
        pid = state["project_id"]
        new_instr: dict[str, str] = {}
        exhausted: Task | None = None
        for t in plan.tasks:
            if t.status != TaskStatus.FAILED:
                continue
            if t.attempts < deps.max_task_attempts:
                new_instr[t.key] = (f"{t.description}\nYour previous attempt was rejected: {t.error}\n"
                                    "Fix these problems; follow the output schema exactly.")
                plan.set_status(t.key, TaskStatus.PENDING)
            elif exhausted is None:
                exhausted = t
        if exhausted is not None:
            decision = TaskDecision.model_validate(interrupt({
                "type": "task_failed", "task_key": exhausted.key, "agent": exhausted.agent.value,
                "attempts": exhausted.attempts, "error": exhausted.error, "options": ["retry", "skip"],
            }))
            async with deps.conn() as conn:
                await audit(conn, pid, "user", "task_failure_decision", {"task": exhausted.key, "action": decision.action})
                if decision.action == "skip":
                    plan.set_status(exhausted.key, TaskStatus.SKIPPED, exhausted.error)
                    await set_task_status_by_key(conn, pid, [exhausted.key], "skipped")
                else:
                    plan.set_status(exhausted.key, TaskStatus.PENDING)
                    exhausted.attempts = 0
                    new_instr[exhausted.key] = f"{exhausted.description}\nPrevious errors: {exhausted.error}"
        return {"plan": dump_plan(plan), "instructions": new_instr}

    # ------------------------------------------------------------ brand review
    async def brand_review(state):
        """MANDATORY approval checkpoint. Read-only before interrupt(): the node
        body re-runs on resume, so nothing non-idempotent may happen above it."""
        pid = state["project_id"]
        async with deps.conn() as conn:
            art = await load_latest(conn, pid, "brand_guideline")
            await set_phase(conn, pid, "waiting_for_approval", "waiting")
        raw = interrupt({
            "type": "brand_review", "artifact_id": str(art.id), "revision": art.content.revision,
            "guideline": art.content.model_dump(mode="json"),
            "options": ["approve", "revise (with feedback)"],
        })
        return {"review_decision": ReviewDecision.model_validate(raw).model_dump(), "phase": "waiting_for_approval"}

    async def apply_review(state):
        pid = state["project_id"]
        d = ReviewDecision.model_validate(state["review_decision"])
        async with deps.conn() as conn:
            art = await load_latest(conn, pid, "brand_guideline")
            if d.action == "approve":
                await approve_artifact(conn, art.id)
                await audit(conn, pid, "user", "brand_approved", {"artifact_id": str(art.id), "revision": art.content.revision})
                if deps.memory:   # approved guideline => long-term brand memory (drafts never are)
                    await remember_safely(conn, deps, pid, "brand", deps.memory.write_brand(
                        conn, user_id=state["user_id"], project_id=pid, guideline=art.content, artifact_id=art.id))
                    await remember_safely(conn, deps, pid, "decision", deps.memory.log_decision(
                        conn, user_id=state["user_id"], project_id=pid,
                        text=f"User approved brand guideline revision {art.content.revision}.", metadata={"revision": art.content.revision}))
                await set_phase(conn, pid, "wireframing", "running")
                return {"brand_approved": True, "phase": "wireframing"}
            await audit(conn, pid, "user", "brand_feedback", {"feedback": d.feedback, "revision": art.content.revision})
            await set_phase(conn, pid, "generating_brand", "running")
        return {"brand_approved": False, "brand_feedback": d.feedback, "clarify_rounds": 0, "clarification": None}

    async def triage_feedback(state):
        """Manager turns free-text feedback into the SMALLEST set of agents to re-run."""
        pid = state["project_id"]
        plan = load_plan(state)
        feedback = state["brand_feedback"]
        async with deps.conn() as conn:
            brand = await load_latest(conn, pid, "brand_guideline")
            bg: BrandGuideline = brand.content  # type: ignore[assignment]
            summary = {"palette": bg.palette.model_dump(), "typography": bg.typography.model_dump(),
                       "tone": bg.personality.tone_of_voice, "positioning": bg.positioning.statement}
            force = state.get("clarify_rounds", 0) >= 2
            mems = await recall_for(conn, deps, pid=pid, uid=state["user_id"], agent="manager.triage_brand_feedback", query=feedback)
            res = await run_agent(
                AGENTS["manager.triage_brand_feedback"], llm=deps.llm, project_id=pid, memories=mems,
                inputs={"feedback": feedback, "current_brand_summary": summary,
                        "agents_in_plan": [t.agent.value for t in plan.tasks if t.status != TaskStatus.SUPERSEDED]},
                instruction="Decide which agents must re-run." + (" Do NOT ask further questions; decide now." if force else ""),
            )
            tri: BrandFeedbackTriage = res.output  # type: ignore[assignment]
            if tri.clarifying_question and tri.confidence < 0.6 and not force:
                await audit(conn, pid, "manager", "clarification_requested", {"question": tri.clarifying_question})
                return {"clarification": tri.clarifying_question}

            keys: set[str] = set()
            per_key: dict[str, str] = {}
            for ag in tri.affected_agents:
                t = plan.active_task(ag.value)
                if t:
                    keys.add(t.key)
                    per_key[t.key] = tri.instructions.get(ag.value, feedback)
            if not keys:  # triage named nothing we have: default to the brand task
                t = plan.active_task("brand_guideline")
                keys.add(t.key)  # type: ignore[union-attr]
                per_key[t.key] = feedback  # type: ignore[union-attr]
            mapping = plan.rerun(keys)
            instr: dict[str, str] = {}
            for old in set(keys) | set(mapping):
                new = mapping.get(old, old)
                msg = per_key.get(old, "Upstream inputs changed; stay consistent with the updated artifacts.")
                instr[new] = f"User feedback: {feedback}\nChange requested: {msg}"
            task_ids = await ensure_tasks(conn, pid, plan.tasks)
            await set_task_status_by_key(conn, pid, mapping.keys(), "superseded")
            await save_artifact(conn, project_id=pid, kind="execution_plan", content=plan)
            await audit(conn, pid, "manager", "feedback_triaged",
                        {"affected": [a.value for a in tri.affected_agents], "rerun": mapping, "plan_version": plan.version})
            if deps.memory:   # the user's decision becomes long-term memory (deduped; old ones get summarized)
                short = " ".join(feedback.split())[:400]
                await remember_safely(conn, deps, pid, "decision", deps.memory.log_decision(
                    conn, user_id=state["user_id"], project_id=pid,
                    text=f"User feedback on brand guideline revision {bg.revision}: \"{short}\". Manager re-ran: "
                         f"{', '.join(sorted(a.value for a in tri.affected_agents))}.", metadata={"revision": bg.revision}))
                try:
                    await deps.memory.summarize_decisions(conn, deps.llm, project_id=pid, user_id=state["user_id"])
                except Exception as e:  # noqa: BLE001
                    await audit(conn, pid, "system", "memory_error", {"op": "summarize", "error": str(e)[:300]})
        return {"plan": dump_plan(plan), "task_ids": task_ids, "instructions": instr, "clarification": None,
                "brand_approved": False, "phase": "generating_brand"}

    async def clarify(state):
        ans = ClarificationAnswer.model_validate(interrupt({"type": "clarification", "question": state["clarification"]}))
        async with deps.conn() as conn:
            await audit(conn, state["project_id"], "user", "clarification_answer", {"answer": ans.answer})
            if deps.memory:   # SESSION-scope: useful context for this conversation only
                await remember_safely(conn, deps, state["project_id"], "session_note", deps.memory.remember(
                    conn, scope="session", user_id=state["user_id"], project_id=state["project_id"],
                    session_id=session_of(state["project_id"]), kind="clarification",
                    content=f"Q: {state['clarification']} A: {ans.answer}"))
        return {"brand_feedback": f"{state['brand_feedback']}\nClarification: {ans.answer}",
                "clarify_rounds": state.get("clarify_rounds", 0) + 1, "clarification": None}

    # ------------------------------------------------------------------ finish
    async def finish(state):
        plan = load_plan(state)
        pending = [t for t in plan.tasks if t.status == TaskStatus.PENDING]
        phase = "build_pending" if pending else "wireframe_complete"
        async with deps.conn() as conn:
            wf = plan.active_task("wireframe")
            if deps.memory and wf and wf.status == TaskStatus.COMPLETED:
                art = await load_latest(conn, state["project_id"], "wireframe")
                if art:
                    await remember_safely(conn, deps, state["project_id"], "architecture", deps.memory.write_architecture(
                        conn, user_id=state["user_id"], project_id=state["project_id"], wireframe=art.content, artifact_id=art.id))
            await set_phase(conn, state["project_id"], phase, "paused" if pending else "idle")
            await audit(conn, state["project_id"], "manager", "stage_finished",
                        {"phase": phase, "pending": [t.key for t in pending]})
        return {"phase": phase}

    return dict(plan=plan_node, worker=worker, collect=collect, consolidate=consolidate,
                handle_failures=handle_failures, brand_review=brand_review, apply_review=apply_review,
                triage_feedback=triage_feedback, clarify=clarify, finish=finish)
