"""Long-term memory over pgvector (Step 4 builds on this).

Rule that makes embedding-model switching safe: vectors from different models
live in different spaces, so search ONLY compares vectors whose embedding_model
equals the active embedder. After a switch, reembed_stale() rebuilds the index
from the relational rows (the vector is rebuildable; the text is the truth).
"""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.llm.embeddings import Embedder


def _vec(v: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in v) + "]"


async def add_memory(
    conn: AsyncConnection,
    embedder: Embedder,
    *,
    user_id: str,
    project_id: UUID | str,
    kind: str,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> UUID:
    [vec] = await embedder.embed_documents([content])
    row = await (
        await conn.execute(
            "INSERT INTO memories (user_id, project_id, kind, content, metadata, embedding, embedding_model) "
            "VALUES (%s, %s::uuid, %s, %s, %s, %s::vector, %s) RETURNING id",
            (
                user_id,
                str(project_id),
                kind,
                content,
                Jsonb(metadata or {}),
                _vec(vec),
                embedder.ref,
            ),
        )
    ).fetchone()
    return row[0]


async def search_memories(
    conn: AsyncConnection,
    embedder: Embedder,
    *,
    project_id: UUID | str,
    query: str,
    kinds: Sequence[str] | None = None,
    k: int = 5,
) -> list[tuple[str, str, float]]:
    """-> [(kind, content, cosine_similarity)] for ACTIVE memories embedded with the current model."""
    qv = await embedder.embed_query(query)
    rows = await (
        await conn.execute(
            "SELECT kind, content, 1 - (embedding <=> %(q)s::vector) AS sim FROM memories "
            "WHERE project_id = %(p)s::uuid AND is_active AND embedding_model = %(m)s "
            "AND (%(kinds)s::text[] IS NULL OR kind = ANY(%(kinds)s::text[])) "
            "ORDER BY embedding <=> %(q)s::vector LIMIT %(k)s",
            {
                "q": _vec(qv),
                "p": str(project_id),
                "m": embedder.ref,
                "kinds": list(kinds) if kinds else None,
                "k": k,
            },
        )
    ).fetchall()
    return [(r[0], r[1], float(r[2])) for r in rows]


async def count_stale(
    conn: AsyncConnection, embedder: Embedder, project_id: UUID | str | None = None
) -> int:
    row = await (
        await conn.execute(
            "SELECT count(*) FROM memories WHERE is_active AND embedding_model IS DISTINCT FROM %s "
            "AND (%s::uuid IS NULL OR project_id = %s::uuid)",
            (
                embedder.ref,
                str(project_id) if project_id else None,
                str(project_id) if project_id else None,
            ),
        )
    ).fetchone()
    return row[0]


async def reembed_stale(conn: AsyncConnection, embedder: Embedder, *, batch: int = 64) -> int:
    """Re-embed active memories made with another model. Idempotent + resumable:
    each batch commits independently and progress is the embedding_model column."""
    done = 0
    while True:
        rows = await (
            await conn.execute(
                "SELECT id, content FROM memories WHERE is_active AND embedding_model IS DISTINCT FROM %s "
                "ORDER BY created_at LIMIT %s",
                (embedder.ref, batch),
            )
        ).fetchall()
        if not rows:
            return done
        vecs = await embedder.embed_documents([r[1] for r in rows])
        for (mid, _), v in zip(rows, vecs, strict=False):
            await conn.execute(
                "UPDATE memories SET embedding = %s::vector, embedding_model = %s WHERE id = %s",
                (_vec(v), embedder.ref, mid),
            )
        done += len(rows)
