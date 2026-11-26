"""GET /v1/projects/{id}/events — live progress as Server-Sent Events.

Contract
--------
* Every event has a monotonically increasing `id`. The browser's EventSource re-sends the last
  id as `Last-Event-ID` when it reconnects, so a refresh or a dropped connection replays exactly
  what was missed (`?after=N` does the same for non-browser clients).
* Rows in `run_events` are the data; Redis pub/sub only wakes the stream up. If Redis is down
  or a message is lost, the stream still delivers via a short polling interval.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from uuid import UUID

import psycopg
import redis.asyncio as aioredis
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import DATABASE_URL, REDIS_URL
from app.events import channel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects", tags=["events"])

BATCH = 200


def _frame(row) -> str:
    id_, ts, type_, stage, status, message, data = row
    payload = {
        "id": id_,
        "ts": ts.isoformat(),
        "type": type_,
        "stage": stage,
        "status": status,
        "message": message,
        "data": data,
    }
    return f"id: {id_}\nevent: {type_}\ndata: {json.dumps(payload)}\n\n"


async def _listen(redis_url: str, project_id: str, wake: asyncio.Event) -> None:
    """Set `wake` whenever the project publishes. Reconnects forever; failures are harmless."""
    while True:
        client = aioredis.from_url(redis_url, socket_connect_timeout=1)
        try:
            async with client.pubsub() as ps:
                await ps.subscribe(channel(project_id))
                async for msg in ps.listen():
                    if msg.get("type") == "message":
                        wake.set()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"event listener retrying: {e}")
            await asyncio.sleep(2)
        finally:
            try:
                await client.aclose()
            except Exception:
                pass


async def event_frames(
    project_id: str,
    after: int,
    *,
    is_disconnected: Callable[[], Awaitable[bool]],
    dsn: str = DATABASE_URL,
    redis_url: str = REDIS_URL,
    poll_s: float = 2.0,
    heartbeat_s: float = 15.0,
) -> AsyncIterator[str]:
    last = after
    wake = asyncio.Event()
    listener = asyncio.create_task(_listen(redis_url, project_id, wake))
    try:
        async with await psycopg.AsyncConnection.connect(dsn, autocommit=True) as conn:
            yield "retry: 3000\n\n"  # open the stream right away; browser reconnect delay
            beat = time.monotonic()
            while not await is_disconnected():
                wake.clear()  # clear BEFORE reading so a ping during the read is not lost
                rows = await (
                    await conn.execute(
                        "SELECT id, ts, type, stage, status, message, data FROM run_events "
                        "WHERE project_id=%s::uuid AND id>%s ORDER BY id LIMIT %s",
                        (project_id, last, BATCH),
                    )
                ).fetchall()
                for row in rows:
                    last = row[0]
                    yield _frame(row)
                if rows:
                    beat = time.monotonic()
                    continue  # drain the backlog before sleeping
                try:
                    await asyncio.wait_for(wake.wait(), timeout=poll_s)
                except TimeoutError:
                    pass
                if time.monotonic() - beat >= heartbeat_s:
                    yield ": ping\n\n"  # keeps proxies from closing an idle stream
                    beat = time.monotonic()
    finally:
        listener.cancel()


@router.get("/{project_id}/events")
async def project_events(
    project_id: UUID,
    request: Request,
    after: int = 0,
    last_event_id: str | None = Header(default=None),
):
    pid = str(project_id)
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        found = await (
            await conn.execute("SELECT 1 FROM projects WHERE id=%s::uuid", (pid,))
        ).fetchone()
    if not found:
        raise HTTPException(status_code=404, detail="Project not found")
    start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
    return StreamingResponse(
        event_frames(pid, start, is_disconnected=request.is_disconnected),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # nginx: do not buffer the stream
        },
    )
