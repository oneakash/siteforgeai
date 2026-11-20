"""Consolidate node: merge research artifacts into the research digest."""

from __future__ import annotations

import logging
from typing import Any

from app.graph.deps import Deps
from app.graph.inputs import RESEARCH_KINDS
from app.graph.nodes.common import State
from app.graph.nodes.digest import build_digest
from app.graph.nodes.memory import remember_safely
from app.store.artifacts import load_latest, save_artifact
from app.store.tasks import audit

logger = logging.getLogger(__name__)


def make_consolidate(deps: Deps):
    async def consolidate(state: State) -> dict[str, Any]:
        logger.info("🔗 [CONSOLIDATE] Merging research artifacts into digest...")
        pid = state["project_id"]
        ids = state.get("artifact_ids", {})

        async with deps.conn() as conn:
            arts: dict[str, Any] = {}
            for kind in RESEARCH_KINDS:
                a = await load_latest(conn, pid, kind)
                if a:
                    arts[kind] = a.content

            src = {k: ids[k] for k in RESEARCH_KINDS if k in ids}
            prev = await load_latest(conn, pid, "research_digest")
            if not (prev and prev.content.source_artifact_ids == src):
                # replay-safe: only save when sources actually changed
                stored = await save_artifact(
                    conn,
                    project_id=pid,
                    kind="research_digest",
                    content=build_digest(arts, src),
                )
                await audit(
                    conn,
                    pid,
                    "manager",
                    "research_consolidated",
                    {
                        "digest_version": stored.version,
                        "sources": src,
                    },
                )
                ids = {**ids, "research_digest": str(stored.id)}

            if deps.memory:
                await remember_safely(
                    conn,
                    deps,
                    pid,
                    "research",
                    deps.memory.write_research(
                        conn,
                        user_id=state["user_id"],
                        project_id=pid,
                        niche=arts.get("niche_report"),
                        audience=arts.get("audience_report"),
                        competitors=arts.get("competitor_report"),
                        seo=arts.get("seo_strategy"),
                    ),
                )

        key = "|".join(state.get("artifact_ids", {}).get(k, "") for k in RESEARCH_KINDS)
        return {
            "digest_for": key,
            "artifact_ids": {"research_digest": ids.get("research_digest", "")},
        }

    return consolidate
