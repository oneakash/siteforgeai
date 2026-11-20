"""Generation nodes: kickoff per-page generation + assemble the site."""

from __future__ import annotations

import logging
from typing import Any

from app.contracts import ExecutionPlan, TaskStatus
from app.contracts.plan import AgentName, Task
from app.contracts.site import DesignTokens, Page, SiteDocument
from app.graph.deps import Deps
from app.graph.nodes.common import GEN_PAGES, State, dump_plan, load_plan
from app.store.artifacts import load_for_task, load_latest, save_artifact
from app.store.tasks import audit, ensure_tasks, set_phase

logger = logging.getLogger(__name__)


def make_kickoff_generation(deps: Deps):
    async def kickoff_generation(state: State) -> dict[str, Any]:
        """Supersede ANY generic website_generation task and create 3
        specific page tasks.
        """
        pid = state["project_id"]
        plan = load_plan(state)

        # Depend on brand_guideline instead of wireframe, since wireframe
        # might be skipped.
        brand = plan.active_task("brand_guideline")
        if brand is None or brand.status != TaskStatus.COMPLETED:
            return {}

        async with deps.conn() as conn:
            # 1. Aggressively supersede ALL existing website gen tasks.
            for t in plan.tasks:
                if t.agent == AgentName.WEBSITE and t.status in (
                    TaskStatus.PENDING,
                    TaskStatus.COMPLETED,
                ):
                    plan.set_status(
                        t.key,
                        TaskStatus.SUPERSEDED,
                        "replaced by per-page generation",
                    )

            # 2. Create the 3 specific page tasks.
            new_tasks = [
                Task(
                    key=k,
                    agent=AgentName.WEBSITE,
                    description=(f"Generate the '{slug}' page based on brand and research"),
                    depends_on=[brand.key],
                )
                for k, slug in GEN_PAGES
            ]
            plan.tasks.extend(new_tasks)

            # 3. Validate and save.
            ExecutionPlan.model_validate(plan.model_dump())
            await save_artifact(conn, project_id=pid, kind="execution_plan", content=plan)
            task_ids = await ensure_tasks(conn, pid, plan.tasks)
            await set_phase(conn, pid, "generating_site", "running")
            await audit(
                conn,
                pid,
                "manager",
                "generation_kicked_off",
                {
                    "tasks": [t.key for t in new_tasks],
                    "plan_version": plan.version,
                },
            )

        return {
            "plan": dump_plan(plan),
            "task_ids": task_ids,
            "phase": "generating_site",
        }

    return kickoff_generation


def make_assemble_site(deps: Deps):
    async def assemble_site(state: State) -> dict[str, Any]:
        """Bundle the generated Page artifacts into the versioned SiteDocument."""
        pid = state["project_id"]
        plan = load_plan(state)

        async with deps.conn() as conn:
            brand_art = await load_latest(conn, pid, "brand_guideline", approved_only=True)
            if not brand_art:
                raise RuntimeError("Approved brand guideline not found")
            brand = brand_art.content

            # Wireframe might be skipped, so handle it gracefully.
            wf_art = await load_latest(conn, pid, "wireframe")
            wire = wf_art.content if wf_art else None

            pages: list[Page] = []
            for t in plan.tasks:
                if t.agent == AgentName.WEBSITE and t.status == TaskStatus.COMPLETED:
                    art = await load_for_task(conn, state["task_ids"][t.key])
                    if art:
                        pages.append(Page.model_validate(art.content))
            if not pages:
                raise RuntimeError("no generated pages found to assemble")
            pages.sort(key=lambda p: 0 if p.slug == "/" else 1)

            have = {p.slug for p in pages}

            nav: list[Any]
            footer_links: list[str]
            if wire:
                nav = [
                    n.model_copy(update={"children": [c for c in n.children if c.slug in have]})
                    for n in wire.navigation
                    if n.slug in have or any(c.slug in have for c in n.children)
                ]
                footer_links = [s for s in wire.footer_links if s in have]
            else:
                nav = [{"label": p.title, "slug": p.slug} for p in pages]
                footer_links = ["/contact", "/about"]

            site_doc = SiteDocument(
                version=1,
                brand_name=brand.brand_name,
                tokens=DesignTokens(
                    colors=brand.palette,
                    heading_font=brand.typography.heading_font,
                    body_font=brand.typography.body_font,
                ),
                navigation=nav,
                footer_links=footer_links,
                pages=pages,
            )
            stored = await save_artifact(
                conn, project_id=pid, kind="site_document", content=site_doc
            )

            qa = plan.active_task("qa")
            if qa and qa.status == TaskStatus.PENDING:
                plan.set_status(
                    qa.key,
                    TaskStatus.SKIPPED,
                    "qa disabled for this milestone",
                )
                await save_artifact(conn, project_id=pid, kind="execution_plan", content=plan)

            await set_phase(conn, pid, "published", "idle")
            await audit(
                conn,
                pid,
                "manager",
                "site_assembled",
                {
                    "version": site_doc.version,
                    "artifact_id": str(stored.id),
                    "pages": sorted(have),
                },
            )

        return {
            "plan": dump_plan(plan),
            "site_document_id": str(stored.id),
            "phase": "published",
        }

    return assemble_site
