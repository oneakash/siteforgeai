"""What each agent is allowed to see: typed artifacts only (no chat history)."""
from typing import Any

from psycopg import AsyncConnection

from app.store.artifacts import load_latest

RESEARCH_KINDS = ["niche_report", "audience_report", "competitor_report", "seo_strategy"]

INPUT_KINDS: dict[str, list[str]] = {
    "niche_analysis": [],
    "audience_research": [],
    "competitor_analysis": [],
    "seo_analysis": [],
    "brand_guideline": RESEARCH_KINDS,
    "wireframe": ["brand_guideline", "seo_strategy", "research_digest"],
}
IMPLEMENTED_AGENTS = set(INPUT_KINDS)          # Steps 5+ add content/design/image/website/qa
RESEARCH_AGENTS = {"niche_analysis", "audience_research", "competitor_analysis", "seo_analysis"}


async def build_inputs(conn: AsyncConnection, *, project_id: str, agent: str, brand_name: str,
                       niche: str, prompt: str, revision: bool) -> dict[str, Any]:
    inputs: dict[str, Any] = {"brand_name": brand_name, "business": {"niche": niche, "prompt": prompt}}
    for kind in INPUT_KINDS[agent]:
        # the wireframe may only build on the APPROVED brand
        art = await load_latest(conn, project_id, kind, approved_only=(agent == "wireframe" and kind == "brand_guideline"))
        if art:
            inputs[kind] = art.content
        elif agent == "wireframe" and kind == "brand_guideline":
            raise RuntimeError("wireframe scheduled before the brand guideline was approved")
    if agent == "brand_guideline" and revision:
        prev = await load_latest(conn, project_id, "brand_guideline")
        if prev:
            inputs["previous_brand_guideline"] = prev.content
    return inputs
