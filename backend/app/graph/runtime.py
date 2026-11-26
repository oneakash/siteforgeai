"""Builds the compiled graph + its dependencies. Shared by the API process and Celery workers."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.config import DATABASE_URL
from app.graph.checkpointer import checkpointer_pool
from app.graph.deps import Deps, get_llm
from app.graph.root import build_root_graph
from app.memory.provider import EmbedderProvider
from app.memory.service import MemoryService


@dataclass
class Runtime:
    saver: Any
    memory: MemoryService
    deps: Deps
    graph: Any


@asynccontextmanager
async def graph_runtime() -> AsyncIterator[Runtime]:
    """One checkpointer pool + one compiled graph. Must be entered INSIDE the event loop that
    will use it (a Celery task builds its own per run; the API builds one at startup)."""
    async with checkpointer_pool() as saver:
        memory = MemoryService(EmbedderProvider())
        deps = Deps(llm=get_llm(), dsn=DATABASE_URL, memory=memory)
        graph = build_root_graph(deps=deps, checkpointer=saver)
        deps.graph = graph
        yield Runtime(saver=saver, memory=memory, deps=deps, graph=graph)
