"""Task ledger (tasks table) + audit trail + phase. All writes are idempotent."""

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.contracts.plan import Task
from app.events import emit, phase_message, task_message


# audit actions worth showing to the user (everything else stays in the audit trail only)
LOGGED_ACTIONS = {
    "plan_created": "Execution plan created",
    "research_consolidated": "Research findings combined",
    "brand_feedback": "Your feedback was received",
    "feedback_triaged": "Working out what to change",
    "brand_approved": "Brand guideline approved",
    "generation_kicked_off": "Page generation started",
    "site_assembled": "Pages assembled into your site",
    "task_failed": "A task failed — the manager is deciding what to do",
    "workflow_error": "Temporary error — the run can be continued",
    "worker_error": "Unexpected error in the worker",
    "run_timeout": "The run timed out and can be continued",
    "stale_resume_dropped": "Ignored a duplicate answer",
}


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
            "WHERE id=%s::uuid AND status NOT IN ('completed','superseded') "
            "RETURNING attempts, project_id, task_key, agent",
            (task_id,),
        )
    ).fetchone()
    if not row:
        return None
    attempts, pid, key, agent = row
    await emit(
        conn,
        str(pid),
        "task",
        task_message(key, agent, "running", attempts),
        stage=key,
        status="running",
        data={"agent": agent, "attempt": attempts},
    )
    return attempts


async def task_attempts(conn: AsyncConnection, task_id: str) -> int:
    return (
        await (
            await conn.execute("SELECT attempts FROM tasks WHERE id=%s::uuid", (task_id,))
        ).fetchone()
    )[0]


async def finish_task(
    conn: AsyncConnection, task_id: str, status: str, error: str | None = None
) -> None:
    row = await (
        await conn.execute(
            "UPDATE tasks SET status=%s, error=%s, completed_at = CASE WHEN %s='completed' THEN now() ELSE completed_at END "
            "WHERE id=%s::uuid RETURNING project_id, task_key, agent, attempts",
            (status, error, status, task_id),
        )
    ).fetchone()
    if row and status in ("completed", "failed"):
        pid, key, agent, attempts = row
        await emit(
            conn,
            str(pid),
            "task",
            task_message(key, agent, status, attempts),
            stage=key,
            status=status,
            data={"agent": agent, "attempt": attempts, **({"error": error[:300]} if error else {})},
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
    row = await (
        await conn.execute(
            "WITH old AS (SELECT phase FROM projects WHERE id=%s::uuid) "
            "UPDATE projects SET phase=%s, status=COALESCE(%s,status), updated_at=now() "
            "WHERE id=%s::uuid RETURNING (SELECT phase FROM old)",
            (project_id, phase, status, project_id),
        )
    ).fetchone()
    if row and row[0] != phase:  # only real transitions become events
        await emit(
            conn,
            str(project_id),
            "phase",
            phase_message(phase),
            stage=phase,
            status=status,
            data={"previous": row[0]},
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
    if action in LOGGED_ACTIONS:
        await emit(
            conn,
            str(project_id),
            "log",
            LOGGED_ACTIONS[action],
            stage=action,
            data={"actor": actor},
        )
