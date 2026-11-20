"""Task ledger (tasks table) + audit trail + phase. All writes are idempotent."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.contracts.plan import Task


async def ensure_tasks(
    conn: AsyncConnection, project_id: UUID | str, tasks: Iterable[Task]
) -> dict[str, str]:
    """Insert ledger rows for planned tasks (no-op for existing). -> {task_key: task_id}."""
    for t in tasks:
        await conn.execute(
            "INSERT INTO tasks (project_id, task_key, agent, status, depends_on) VALUES (%s::uuid,%s,%s,%s,%s) "
            "ON CONFLICT (project_id, task_key) DO NOTHING",
            (str(project_id), t.key, t.agent.value, t.status.value, Jsonb(t.depends_on)),
        )
    rows = await (
        await conn.execute(
            "SELECT task_key, id FROM tasks WHERE project_id=%s::uuid", (str(project_id),)
        )
    ).fetchall()
    return {k: str(i) for k, i in rows}


async def claim_task(conn: AsyncConnection, task_id: str) -> int | None:
    """Mark running + bump attempts. Returns the attempt number, or None if the
    task is already COMPLETED (=> caller must not execute it again)."""
    row = await (
        await conn.execute(
            "UPDATE tasks SET status='running', attempts=attempts+1, started_at=COALESCE(started_at, now()), error=NULL "
            "WHERE id=%s::uuid AND status NOT IN ('completed','superseded') RETURNING attempts",
            (task_id,),
        )
    ).fetchone()
    return row[0] if row else None


async def task_attempts(conn: AsyncConnection, task_id: str) -> int:
    return (
        await (
            await conn.execute("SELECT attempts FROM tasks WHERE id=%s::uuid", (task_id,))
        ).fetchone()
    )[0]


async def finish_task(
    conn: AsyncConnection, task_id: str, status: str, error: str | None = None
) -> None:
    await conn.execute(
        "UPDATE tasks SET status=%s, error=%s, completed_at = CASE WHEN %s='completed' THEN now() ELSE completed_at END "
        "WHERE id=%s::uuid",
        (status, error, status, task_id),
    )


async def set_task_status_by_key(
    conn: AsyncConnection, project_id: str, keys: Iterable[str], status: str
) -> None:
    for k in keys:
        await conn.execute(
            "UPDATE tasks SET status=%s WHERE project_id=%s::uuid AND task_key=%s",
            (status, project_id, k),
        )


async def set_phase(
    conn: AsyncConnection, project_id: str, phase: str, status: str | None = None
) -> None:
    await conn.execute(
        "UPDATE projects SET phase=%s, status=COALESCE(%s,status), updated_at=now() WHERE id=%s::uuid",
        (phase, status, project_id),
    )


async def audit(
    conn: AsyncConnection,
    project_id: str,
    actor: str,
    action: str,
    payload: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO audit_log (project_id, actor, action, payload) VALUES (%s::uuid,%s,%s,%s)",
        (project_id, actor, action, Jsonb(payload or {})),
    )
