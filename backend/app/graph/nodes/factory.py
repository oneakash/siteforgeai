"""Factory that wires all node constructors into a single mapping."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.graph.deps import Deps
from app.graph.nodes.brand_review import make_apply_review, make_brand_review
from app.graph.nodes.collect import make_collect
from app.graph.nodes.consolidate import make_consolidate
from app.graph.nodes.failures import make_handle_failures
from app.graph.nodes.finish import make_finish
from app.graph.nodes.generation import make_assemble_site, make_kickoff_generation
from app.graph.nodes.planning import make_plan_node
from app.graph.nodes.triage import make_clarify, make_triage_feedback
from app.graph.nodes.worker import make_worker

Node = Callable[..., Any]


def make_nodes(deps: Deps) -> dict[str, Node]:
    """Return the mapping of node names to LangGraph node callables."""
    return {
        "plan": make_plan_node(deps),
        "worker": make_worker(deps),
        "collect": make_collect(deps),
        "consolidate": make_consolidate(deps),
        "handle_failures": make_handle_failures(deps),
        "brand_review": make_brand_review(deps),
        "apply_review": make_apply_review(deps),
        "triage_feedback": make_triage_feedback(deps),
        "clarify": make_clarify(deps),
        "finish": make_finish(deps),
        "kickoff_generation": make_kickoff_generation(deps),
        "assemble_site": make_assemble_site(deps),
    }
