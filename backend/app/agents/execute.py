"""execute_task = ledger-safe wrapper: skip if done, run, validate, persist."""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.agents.llm import StructuredLLM
from app.agents.registry import AgentSpec
from app.agents.runner import run_agent
from app.store.artifacts import StoredArtifact, load_for_task, save_artifact

@dataclass
class TaskExecution:
    artifact: StoredArtifact
    skipped: bool  # True => artifact already existed; the LLM was NOT called
    attempts: int
    model: str | None = None

async def execute_task(
    conn: AsyncConnection,
    *,
    project_id: UUID | str,
    task_id: UUID | str,
    spec: AgentSpec,
    llm: StructuredLLM,
    inputs: Mapping[str, Any],
    memories: Sequence[tuple[str, str]] = (),
    instruction: str = "",
    to_artifact: Callable[[BaseModel], BaseModel] | None = None,
    kind: str | None = None,
) -> TaskExecution:
    existing = await load_for_task(conn, task_id)
    if existing:  # recovery path: never pay for the same work twice
        return TaskExecution(existing, True, 0, None)
    result = await run_agent(
        spec,
        llm=llm,
        inputs=inputs,
        memories=memories,
        instruction=instruction,
        project_id=project_id,
    )
    content = to_artifact(result.output) if to_artifact else result.output
    stored = await save_artifact(
        conn,
        project_id=project_id,
        task_id=task_id,
        kind=kind or spec.artifact_kind,
        content=content,
    )
    await conn.execute(  # audit trail: which model produced this artifact
        "INSERT INTO audit_log (project_id, actor, action, payload) VALUES (%s::uuid, %s, 'agent_completed', %s)",
        (
            str(project_id),
            spec.name,
            Jsonb(
                {
                    "kind": stored.kind,
                    "version": stored.version,
                    "model": result.model,
                    "attempts": result.attempts,
                    "searches": result.searches,
                }
            ),
        ),
    )
    return TaskExecution(stored, False, result.attempts, result.model)