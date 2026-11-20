"""Idempotent artifact persistence (psycopg async). Postgres is the source of truth."""

from dataclasses import dataclass
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from app.contracts import ARTIFACT_MODELS


@dataclass(frozen=True)
class StoredArtifact:
    id: UUID
    kind: str
    version: int
    approved: bool
    content: BaseModel
    created_now: bool  # False => an existing row was returned (idempotent no-op)


def _model_for(kind: str) -> type[BaseModel]:
    try:
        return ARTIFACT_MODELS[kind]
    except KeyError:
        raise KeyError(f"unknown artifact kind '{kind}'") from None


async def save_artifact(
    conn: AsyncConnection,
    *,
    project_id: UUID | str,
    kind: str,
    content: BaseModel,
    task_id: UUID | str | None = None,
) -> StoredArtifact:
    """Insert a new artifact version. If `task_id` already produced one, return
    it unchanged (double-write after crash recovery is a no-op)."""
    payload = Jsonb(content.model_dump(mode="json"))
    for _ in range(5):  # retry only on a version race between concurrent writers
        row = await (
            await conn.execute(
                """
                INSERT INTO artifacts (project_id, task_id, kind, version, content)
                SELECT %(p)s::uuid, %(t)s::uuid, %(k)s, COALESCE(MAX(version), 0) + 1, %(c)s
                FROM artifacts WHERE project_id = %(p)s::uuid AND kind = %(k)s
                ON CONFLICT DO NOTHING
                RETURNING id, version, approved
                """,
                {
                    "p": str(project_id),
                    "t": str(task_id) if task_id else None,
                    "k": kind,
                    "c": payload,
                },
            )
        ).fetchone()
        if row:
            return StoredArtifact(row[0], kind, row[1], row[2], content, True)
        if task_id:
            existing = await load_for_task(conn, task_id)
            if existing:
                return existing
    raise RuntimeError(f"could not store artifact '{kind}' (persistent version conflict)")


def _row_to_artifact(row, created_now: bool = False) -> StoredArtifact:
    id_, kind, version, approved, content = row
    return StoredArtifact(
        id_, kind, version, approved, _model_for(kind).model_validate(content), created_now
    )


async def load_for_task(conn: AsyncConnection, task_id: UUID | str) -> StoredArtifact | None:
    row = await (
        await conn.execute(
            "SELECT id, kind, version, approved, content FROM artifacts WHERE task_id = %s::uuid",
            (str(task_id),),
        )
    ).fetchone()
    return _row_to_artifact(row) if row else None


async def load_latest(
    conn: AsyncConnection, project_id: UUID | str, kind: str, *, approved_only: bool = False
) -> StoredArtifact | None:
    row = await (
        await conn.execute(
            "SELECT id, kind, version, approved, content FROM artifacts "
            "WHERE project_id = %s::uuid AND kind = %s "
            + ("AND approved " if approved_only else "")
            + "ORDER BY version DESC LIMIT 1",
            (str(project_id), kind),
        )
    ).fetchone()
    return _row_to_artifact(row) if row else None


async def approve_artifact(conn: AsyncConnection, artifact_id: UUID | str) -> None:
    await conn.execute(
        "UPDATE artifacts SET approved = true WHERE id = %s::uuid", (str(artifact_id),)
    )
