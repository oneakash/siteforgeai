"""Per-project run lock (Postgres advisory lock).

Celery delivers at-least-once, so the same project can be handed to two workers (redelivery
after a crash, a double-clicked button). Two concurrent runs on one LangGraph thread would
corrupt each other. A SESSION-level advisory lock is held on a dedicated connection for the
whole run; if the worker dies, Postgres drops the connection and the lock is released.

Not compatible with PgBouncer in transaction-pooling mode (session state is not preserved).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import psycopg

_KEY_SQL = "hashtextextended(%s, 0)"


def _name(project_id: str) -> str:
    return f"siteforge:run:{project_id}"


@asynccontextmanager
async def project_lock(dsn: str, project_id: str) -> AsyncIterator[bool]:
    """Yields True if this caller now owns the project's run lock, else False (never blocks)."""
    async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
        row = await (
            await conn.execute(f"SELECT pg_try_advisory_lock({_KEY_SQL})", (_name(project_id),))
        ).fetchone()
        acquired = bool(row[0])
        try:
            yield acquired
        finally:
            if acquired:
                await conn.execute(f"SELECT pg_advisory_unlock({_KEY_SQL})", (_name(project_id),))
