from contextlib import asynccontextmanager
from dataclasses import dataclass

from psycopg import AsyncConnection

from app.agents.llm import StructuredLLM


@dataclass
class Deps:
    llm: StructuredLLM
    dsn: str
    max_task_attempts: int = 3   # manager-level retries before asking the user
    max_corrections: int = 2     # validator re-prompts inside run_agent

    @asynccontextmanager
    async def conn(self):
        async with await AsyncConnection.connect(self.dsn, autocommit=True) as c:
            yield c
