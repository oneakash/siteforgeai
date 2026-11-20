"""Scenario : kill the process mid-workflow, restart, continue.

  python -m scripts.recovery_demo start   --crash-on AudienceReport     (process #1 dies with exit 137)
  python -m scripts.recovery_demo continue --project <id>               (process #2 resumes)
  python -m scripts.recovery_demo approve  --project <id>
Runs with the deterministic DemoLLM, so no API key is needed.
"""

import argparse
import asyncio
import json

from app.config import DATABASE_URL
from app.demo.demo_embedder import DemoEmbedder
from app.demo.demo_llm import DemoLLM
from app.graph import service
from app.graph.checkpointer import checkpointer_pool
from app.graph.deps import Deps
from app.graph.root import build_root_graph
from app.memory.provider import StaticEmbedderProvider
from app.memory.service import MemoryService


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["start", "continue", "approve"])
    p.add_argument("--project")
    p.add_argument("--crash-on")
    p.add_argument("--marker", default="/tmp/siteforge_crash_marker")
    a = p.parse_args()
    llm = DemoLLM(delay=0.2, crash_on=a.crash_on, crash_marker=a.marker)
    deps = Deps(
        llm=llm,
        dsn=DATABASE_URL,
        memory=MemoryService(StaticEmbedderProvider(DemoEmbedder("demo:bow"))),
    )
    async with checkpointer_pool() as saver:
        graph = build_root_graph(deps, saver)
        if a.cmd == "start":
            out = await service.start_project(
                graph,
                deps,
                user_id="demo",
                brand_name="Aurum Escapes",
                prompt="Luxury private travel",
                niche="Travel",
            )
        elif a.cmd == "continue":
            out = await service.continue_run(graph, deps, a.project)
        else:
            out = await service.resume(graph, deps, a.project, {"action": "approve"})
    print(
        "RESULT",
        json.dumps(
            {k: out.get(k) for k in ("project_id", "phase", "next")}
            | {"waiting": (out.get("waiting_for") or {}).get("type")}
        ),
    )


if __name__ == "__main__":
    asyncio.run(main())
