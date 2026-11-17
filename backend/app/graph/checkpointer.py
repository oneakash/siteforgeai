"""Postgres-backed LangGraph checkpointer (the *only* workflow-state store)."""
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.config import DATABASE_URL


@asynccontextmanager
async def checkpointer_pool():
    """Yield a ready AsyncPostgresSaver backed by a connection pool.

    autocommit + dict_row are required by the saver. prepare_threshold=0
    avoids prepared-statement clashes when pooled connections are reused.
    """
    pool = AsyncConnectionPool(
        conninfo=DATABASE_URL,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)
        await saver.setup()  # creates checkpoint tables (idempotent)
        yield saver
    finally:
        await pool.close()
