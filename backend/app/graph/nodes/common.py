"""Shared helpers and constants for graph nodes.

Graph nodes must obey three rules:
  * idempotent: safe to re-run after a crash or an interrupt resume
  * side effects go through the ledger / artifact store (unique keys)
  * state carries ids and small control data, never bulky artifacts
"""

from __future__ import annotations

from typing import Any

from app.contracts import ExecutionPlan

State = dict[str, Any]

PHASE_FOR_AGENT: dict[str, str] = {
    "brand_guideline": "generating_brand",
    "wireframe": "wireframing",
}

GEN_PAGES: list[tuple[str, str]] = [
    ("gen_home", "/"),
    ("gen_about", "/about"),
    ("gen_contact", "/contact"),
]


def session_of(project_id: str) -> str:
    """Return the LangGraph thread_id for a project."""
    return f"proj-{project_id}"


def load_plan(state: State) -> ExecutionPlan:
    return ExecutionPlan.model_validate(state["plan"])


def dump_plan(plan: ExecutionPlan) -> dict[str, Any]:
    return plan.model_dump(mode="json")
