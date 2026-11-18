import contextlib

import psycopg
import pytest

from app.config import DATABASE_URL
from app.demo.demo_embedder import DemoEmbedder
from app.demo.demo_llm import DemoLLM
from app.memory.provider import StaticEmbedderProvider
from app.memory.service import MemoryService
from app.graph.checkpointer import checkpointer_pool
from app.graph.deps import Deps
from app.graph.root import build_root_graph
from langgraph.types import RetryPolicy
from app.agents.errors import TransientAgentError

FAST_RETRY = RetryPolicy(max_attempts=3, initial_interval=0.01, backoff_factor=1.0, jitter=False, retry_on=TransientAgentError)


@contextlib.asynccontextmanager
async def make_env(llm: DemoLLM, memory="default", **deps_kw):
    if memory == "default":
        memory = MemoryService(StaticEmbedderProvider(DemoEmbedder("demo:bow")))
    deps = Deps(llm=llm, dsn=DATABASE_URL, memory=memory, **deps_kw)
    async with checkpointer_pool() as saver:
        yield build_root_graph(deps, saver, retry=FAST_RETRY), deps


async def q(sql, params=()):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as c:
        return await (await c.execute(sql, params)).fetchall()
