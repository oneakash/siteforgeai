import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from psycopg import AsyncConnection

from app.agents.llm import StructuredLLM, FakeLLM
from app.config import DATABASE_URL
from app.llm.router import ModelRouter


@dataclass
class Deps:
    llm: StructuredLLM
    dsn: str
    max_task_attempts: int = 3   # manager-level retries before asking the user
    max_corrections: int = 2     # validator re-prompts inside run_agent
    memory: Any = None           # MemoryService | None (None => memory features are no-ops)
    graph: Any = None            # The compiled LangGraph instance

    @asynccontextmanager
    async def conn(self):
        async with await AsyncConnection.connect(self.dsn, autocommit=True) as c:
            yield c


def get_llm() -> StructuredLLM:
    """Factory for the LLM. Falls back to FakeLLM if no API keys are configured."""
    has_key = any(os.environ.get(k) for k in ("NVIDIA_API_KEY", "GROQ_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY"))
    
    if not has_key:
        print("\n⚠️ WARNING: No LLM API keys found in environment. Using FakeLLM for development.")
        print("   -> To generate real websites, add NVIDIA_API_KEY, GROQ_API_KEY, or GOOGLE_API_KEY to your .env file.\n")
        
        # Provide a fully valid ExecutionPlan for the first 'manager.plan' call 
        # so the graph can start without crashing immediately.
        from app.contracts.plan import ExecutionPlan, Task, AgentName
        
        dummy_plan = ExecutionPlan(
            version=1,
            goal="Generate a basic website for local development testing",
            website_purpose="Demo site to validate the pipeline",
            business_model="Local testing",
            expected_functionality=["Basic landing page", "Contact form"],
            rationale="Fallback plan for zero-key development environment",
            tasks=[
                Task(key="research_niche", agent=AgentName.NICHE, description="Analyze niche", depends_on=[]),
                Task(key="research_audience", agent=AgentName.AUDIENCE, description="Analyze audience", depends_on=[]),
                Task(key="brand_guideline", agent=AgentName.BRAND, description="Create brand guideline", depends_on=["research_niche", "research_audience"]),
            ]
        )
        return FakeLLM(script=[dummy_plan])
    
    return ModelRouter()


async def get_deps(request: Request) -> Deps:
    """
    FastAPI dependency injector. 
    Reads the compiled graph and memory from app.state (set in main.py).
    """
    return Deps(
        llm=get_llm(),
        dsn=DATABASE_URL,
        memory=getattr(request.app.state, "memory", None),
        graph=request.app.state.graph,
    )