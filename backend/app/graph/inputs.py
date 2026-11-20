"""What each agent is allowed to see: typed artifacts only (no chat history)."""

from typing import Any

from psycopg import AsyncConnection

from app.store.artifacts import load_latest

RESEARCH_KINDS = ["niche_report", "audience_report", "competitor_report", "seo_strategy"]

# task_key suffix -> page slug for the website_generation fan-out (kickoff_generation)
PAGE_SLUG_BY_TASK = {"home": "/", "about": "/about", "contact": "/contact"}

INPUT_KINDS: dict[str, list[str]] = {
    "niche_analysis": [],
    "audience_research": [],
    "competitor_analysis": [],
    "seo_analysis": [],
    "brand_guideline": RESEARCH_KINDS,
    "wireframe": ["brand_guideline", "seo_strategy", "research_digest"],
    "website_generation": ["wireframe", "brand_guideline", "research_digest"],
}

IMPLEMENTED_AGENTS = set(INPUT_KINDS)
RESEARCH_AGENTS = {"niche_analysis", "audience_research", "competitor_analysis", "seo_analysis"}


async def build_inputs(
    conn: AsyncConnection,
    *,
    project_id: str,
    agent: str,
    brand_name: str,
    niche: str,
    prompt: str,
    revision: bool,
    task_key: str = "",
) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "brand_name": brand_name,
        "business": {"niche": niche, "prompt": prompt},
    }
    for kind in INPUT_KINDS[agent]:
        approved = agent in ("wireframe", "website_generation") and kind == "brand_guideline"
        art = await load_latest(conn, project_id, kind, approved_only=approved)
        if art:
            inputs[kind] = art.content
        elif agent == "wireframe" and kind == "brand_guideline":
            raise RuntimeError("wireframe scheduled before the brand guideline was approved")

    if agent == "website_generation":
        wf = inputs.get("wireframe")
        suffix = task_key.split("_", 1)[-1] if "_" in task_key else ""
        slug = PAGE_SLUG_BY_TASK.get(suffix)

        if wf and slug:
            page = next((p for p in wf.pages if p.slug == slug), None)
            if page:
                # Only pass slug, title, and purpose. DO NOT pass sections so the LLM is forced to generate them.
                inputs["page_spec"] = {
                    "slug": page.slug,
                    "title": page.title,
                    "purpose": page.purpose,
                }
            else:
                inputs["page_spec"] = {
                    "slug": slug,
                    "title": slug.replace("/", " ").title(),
                    "purpose": f"Generate content for {slug}",
                }
        else:
            # No wireframe at all, provide a basic template
            inputs["page_spec"] = {
                "slug": slug,
                "title": slug.replace("/", " ").title() if slug else "Home",
                "purpose": f"Generate content for {slug}",
            }

        inputs["slug"] = slug
        inputs["title"] = inputs["page_spec"]["title"]

    if agent == "brand_guideline" and revision:
        prev = await load_latest(conn, project_id, "brand_guideline")
        if prev:
            inputs["previous_brand_guideline"] = prev.content
    return inputs
