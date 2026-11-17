"""The root LangGraph.

  START -> plan -> [route] -+-> research (SUBGRAPH, parallel fan-out) -+
                            +-> worker x N (brand / wireframe, Send)  -+-> collect -> [route]
                            +-> consolidate ----------------------------------------> [route]
                            +-> handle_failures (retry | interrupt) ----------------> [route]
                            +-> brand_review (INTERRUPT) -> apply_review -+-> [route] (approved)
                            |                                              +-> triage_feedback -+-> [route] (re-run only what changed)
                            |                                                                   +-> clarify (INTERRUPT) -> triage_feedback
                            +-> finish -> END
"""
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from app.agents.errors import TransientAgentError
from app.contracts import ExecutionPlan, TaskStatus
from app.graph.deps import Deps
from app.graph.inputs import IMPLEMENTED_AGENTS, RESEARCH_AGENTS, RESEARCH_KINDS
from app.graph.nodes import load_plan, make_nodes
from app.graph.state import ResearchState, RootState

DEFAULT_RETRY = RetryPolicy(max_attempts=3, initial_interval=1.0, backoff_factor=2.0, max_interval=20.0,
                            jitter=True, retry_on=TransientAgentError)


def build_root_graph(deps: Deps, checkpointer, retry: RetryPolicy = DEFAULT_RETRY):
    n = make_nodes(deps)

    # ---------------- research SUBGRAPH: parallel fan-out of research workers
    def fan_out(state: ResearchState):
        base = {k: state[k] for k in ("project_id", "user_id", "brand_name", "prompt", "niche")}  # type: ignore[literal-required]
        return [Send("research_worker", {**base, **spec}) for spec in state["specs"]]

    sub = StateGraph(ResearchState)
    sub.add_node("research_worker", n["worker"], retry_policy=retry)
    sub.add_conditional_edges(START, fan_out, ["research_worker"])
    sub.add_edge("research_worker", END)
    research = sub.compile()

    # ---------------- scheduler: the Manager's parallel-vs-sequential decision
    def route(state: RootState):
        plan: ExecutionPlan = load_plan(state)
        live = [t for t in plan.tasks if t.status != TaskStatus.SUPERSEDED]

        if any(t.status == TaskStatus.FAILED for t in live):
            return "handle_failures"

        research_done = [t for t in live if t.agent.value in RESEARCH_AGENTS]
        digest_key = "|".join(state.get("artifact_ids", {}).get(k, "") for k in RESEARCH_KINDS)
        if (research_done and all(t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED) for t in research_done)
                and digest_key != state.get("digest_for")):
            return "consolidate"

        brand = plan.active_task("brand_guideline")
        if brand and brand.status == TaskStatus.COMPLETED and not state.get("brand_approved"):
            return "brand_review"   # nothing downstream may run before approval

        ready = [t for t in plan.ready_tasks() if t.agent.value in IMPLEMENTED_AGENTS]
        if not ready:
            return "finish"

        base = {k: state[k] for k in ("project_id", "user_id", "brand_name", "prompt", "niche")}  # type: ignore[literal-required]
        instr = state.get("instructions", {})

        def spec(t):
            return {"task_key": t.key, "task_id": state["task_ids"][t.key], "agent": t.agent.value,
                    "instruction": instr.get(t.key, t.description), "is_revision": t.key in instr}

        sends = []
        r = [spec(t) for t in ready if t.agent.value in RESEARCH_AGENTS]
        if r:  # all ready research tasks run in parallel inside ONE subgraph invocation
            sends.append(Send("research", {**base, "specs": r}))
        sends += [Send("worker", {**base, **spec(t)}) for t in ready if t.agent.value not in RESEARCH_AGENTS]
        return sends

    def after_review(state: RootState):
        return route(state) if state.get("review_decision", {}).get("action") == "approve" else "triage_feedback"

    def after_triage(state: RootState):
        return "clarify" if state.get("clarification") else route(state)

    g = StateGraph(RootState)
    g.add_node("plan", n["plan"], retry_policy=retry)
    g.add_node("research", research)
    g.add_node("worker", n["worker"], retry_policy=retry)
    g.add_node("collect", n["collect"])
    g.add_node("consolidate", n["consolidate"])
    g.add_node("handle_failures", n["handle_failures"])
    g.add_node("brand_review", n["brand_review"])
    g.add_node("apply_review", n["apply_review"])
    g.add_node("triage_feedback", n["triage_feedback"], retry_policy=retry)
    g.add_node("clarify", n["clarify"])
    g.add_node("finish", n["finish"])

    dests = ["research", "worker", "consolidate", "handle_failures", "brand_review", "finish"]
    g.add_edge(START, "plan")
    for src in ("plan", "collect", "consolidate", "handle_failures"):
        g.add_conditional_edges(src, route, dests)
    g.add_edge("research", "collect")
    g.add_edge("worker", "collect")
    g.add_edge("brand_review", "apply_review")
    g.add_conditional_edges("apply_review", after_review, dests + ["triage_feedback"])
    g.add_conditional_edges("triage_feedback", after_triage, dests + ["clarify"])
    g.add_edge("clarify", "triage_feedback")
    g.add_edge("finish", END)
    return g.compile(checkpointer=checkpointer)
