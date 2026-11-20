"""Brand-review nodes: mandatory approval checkpoint + applying decisions."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from app.graph.deps import Deps
from app.graph.nodes.common import State
from app.graph.nodes.memory import remember_safely
from app.graph.state import ReviewDecision
from app.store.artifacts import approve_artifact, load_latest
from app.store.tasks import audit, set_phase

logger = logging.getLogger(__name__)


def make_brand_review(deps: Deps):
    async def brand_review(state: State) -> dict[str, Any]:
        """MANDATORY approval checkpoint.

        Read-only before ``interrupt()``: the node body re-runs on resume,
        so nothing non-idempotent may happen above it.
        """
        logger.info("🛑 [BRAND REVIEW] Hitting interrupt. Waiting for user approval...")
        pid = state["project_id"]
        async with deps.conn() as conn:
            art = await load_latest(conn, pid, "brand_guideline")
            if not art:
                raise RuntimeError("Brand guideline not found for review")
            await set_phase(conn, pid, "waiting_for_approval", "waiting")
        raw = interrupt(
            {
                "type": "brand_review",
                "artifact_id": str(art.id),
                "revision": art.content.revision,
                "guideline": art.content.model_dump(mode="json"),
                "options": ["approve", "revise (with feedback)"],
            }
        )
        return {
            "review_decision": ReviewDecision.model_validate(raw).model_dump(),
            "phase": "waiting_for_approval",
        }

    return brand_review


def make_apply_review(deps: Deps):
    async def apply_review(state: State) -> dict[str, Any]:
        pid = state["project_id"]
        d = ReviewDecision.model_validate(state["review_decision"])

        async with deps.conn() as conn:
            art = await load_latest(conn, pid, "brand_guideline")

            if d.action == "approve":
                logger.info("✅ [BRAND REVIEW] User APPROVED the brand guideline.")
                await approve_artifact(conn, art.id)
                await audit(
                    conn,
                    pid,
                    "user",
                    "brand_approved",
                    {
                        "artifact_id": str(art.id),
                        "revision": art.content.revision,
                    },
                )
                if deps.memory:
                    # Approved guideline => long-term brand memory
                    # (drafts never are).
                    await remember_safely(
                        conn,
                        deps,
                        pid,
                        "brand",
                        deps.memory.write_brand(
                            conn,
                            user_id=state["user_id"],
                            project_id=pid,
                            guideline=art.content,
                            artifact_id=art.id,
                        ),
                    )
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
                                "User approved brand guideline revision " f"{art.content.revision}."
                            ),
                            metadata={"revision": art.content.revision},
                        ),
                    )
                await set_phase(conn, pid, "wireframing", "running")
                return {"brand_approved": True, "phase": "wireframing"}

            logger.info(f"🔄 [BRAND REVIEW] User requested CHANGES: {d.feedback}")
            await audit(
                conn,
                pid,
                "user",
                "brand_feedback",
                {"feedback": d.feedback, "revision": art.content.revision},
            )
            await set_phase(conn, pid, "generating_brand", "running")

        return {
            "brand_approved": False,
            "brand_feedback": d.feedback,
            "clarify_rounds": 0,
            "clarification": None,
        }

    return apply_review
