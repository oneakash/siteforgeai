"""Memory inspection + user-level preferences (the UI's 'what does the system remember?' panel)."""
from typing import Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import DATABASE_URL
from app.memory.store import reembed_stale

router = APIRouter(tags=["memory"])


def _svc(request: Request):
    return request.app.state.memory


def _out(m):
    return {"id": str(m.id), "scope": m.scope, "kind": m.kind, "topic": m.topic_key, "version": m.version,
            "active": m.is_active, "content": m.content, "similarity": m.similarity, "metadata": m.metadata}


async def _owner(conn, project_id: UUID) -> str:
    row = await (await conn.execute("SELECT user_id FROM projects WHERE id=%s", (project_id,))).fetchone()
    if not row:
        raise HTTPException(404, "project not found")
    return row[0]


@router.get("/v1/projects/{project_id}/memories")
async def list_memories(project_id: UUID, request: Request, kind: Optional[str] = None, history: bool = False):
    """history=true also returns superseded versions (the audit trail of how a fact changed)."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        await _owner(conn, project_id)
        mems = await _svc(request).list_memories(conn, project_id=project_id, include_inactive=history, kind=kind)
    return [_out(m) for m in mems]


@router.get("/v1/projects/{project_id}/memories/search")
async def search(project_id: UUID, request: Request, q: str, k: int = 5):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        uid = await _owner(conn, project_id)
        mems = await _svc(request).recall(conn, project_id=project_id, user_id=uid, query=q, k=k)
    return [_out(m) for m in mems]


class PreferenceIn(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    topic_key: Optional[str] = Field(default=None, pattern=r"^pref\.[a-z0-9_.]+$")


@router.post("/v1/users/{user_id}/preferences")
async def add_preference(user_id: str, body: PreferenceIn, request: Request):
    """Remembered across ALL of this user's future projects. Reuse a topic_key to replace an older preference."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        r = await _svc(request).add_preference(conn, user_id=user_id, text=body.text, topic_key=body.topic_key)
    return {"status": r.status, "id": str(r.id), "version": r.version, "embedded": r.embedded}


@router.post("/v1/memories/reembed")
async def reembed(request: Request):
    """After switching the (system-wide) embedding model: rebuild vectors from the stored text.
    Idempotent and resumable: progress is tracked by memories.embedding_model."""
    svc = _svc(request)
    try:
        emb = await svc.embedders.get(None)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"embedding model unavailable: {e}")
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        return {"reembedded": await reembed_stale(conn, emb), "embedding_model": emb.ref}
