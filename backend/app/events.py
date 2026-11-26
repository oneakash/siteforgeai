"""Progress events: Postgres is the record, Redis pub/sub is only a wake-up signal.

emit()   inserts a row in run_events (durable, ordered by id), then pings Redis.
         It NEVER raises: losing a progress message must not fail a workflow run.
stream   (app/api/events.py) replays rows after a given id, then tails; a Redis ping just makes
         the tail instant. If Redis is down the stream still works (it falls back to polling).
"""

import asyncio
import logging
import time
from typing import Any

import redis
from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from app.config import REDIS_URL

logger = logging.getLogger(__name__)

PHASE_LABELS = {
    "queued": "Queued — waiting for a worker",
    "planning": "Planning the project",
    "researching": "Researching niche, audience, competitors and SEO",
    "consolidating": "Combining research findings",
    "generating_brand": "Designing the brand guideline",
    "waiting_for_approval": "Waiting for your review",
    "wireframing": "Creating the wireframe",
    "generating_site": "Generating site pages",
    "wireframe_complete": "Wireframe complete",
    "build_pending": "Paused — more work pending",
    "published": "Your site is ready",
}
AGENT_LABELS = {
    "niche_analysis": "Niche analysis",
    "audience_research": "Audience research",
    "competitor_analysis": "Competitor analysis",
    "seo_analysis": "SEO analysis",
    "brand_guideline": "Brand guideline",
    "wireframe": "Wireframe",
    "website_generation": "Page generation",
}
_VERBS = {
    "running": "started",
    "completed": "finished",
    "failed": "failed",
    "skipped": "skipped",
    "superseded": "replaced",
}


def channel(project_id: str) -> str:
    return f"siteforge:events:{project_id}"


def phase_message(phase: str) -> str:
    return PHASE_LABELS.get(phase, phase.replace("_", " ").capitalize())


def task_message(task_key: str, agent: str, status: str, attempt: int | None) -> str:
    label = AGENT_LABELS.get(agent, agent.replace("_", " ").capitalize())
    if agent == "website_generation" and task_key.startswith("gen_"):
        label = f"{task_key[4:].capitalize()} page"
    msg = f"{label} {_VERBS.get(status, status)}"
    if status == "running" and attempt and attempt > 1:
        msg += f" (attempt {attempt})"
    return msg


# --- Redis side: sync client in a thread (loop-agnostic; Celery makes a new loop per task) ---
_client: redis.Redis | None = None
_down_until = 0.0  # circuit breaker: after a failure, skip publishing for a few seconds


def _publish(project_id: str, event_id: int) -> None:
    global _client
    _client = _client or redis.Redis.from_url(
        REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5
    )
    _client.publish(channel(project_id), str(event_id))


async def notify(project_id: str, event_id: int) -> None:
    global _down_until
    if time.monotonic() < _down_until:
        return
    try:
        await asyncio.to_thread(_publish, project_id, event_id)
    except Exception as e:  # Redis down: streams fall back to polling the table
        _down_until = time.monotonic() + 5
        logger.debug(f"event notify skipped (redis): {e}")


async def emit(
    conn: AsyncConnection,
    project_id: str,
    type_: str,
    message: str,
    *,
    stage: str | None = None,
    status: str | None = None,
    data: dict[str, Any] | None = None,
) -> int | None:
    try:
        # own transaction (or savepoint): a failed insert can't poison the caller's transaction
        async with conn.transaction():
            row = await (
                await conn.execute(
                    "INSERT INTO run_events (project_id, type, stage, status, message, data) "
                    "VALUES (%s::uuid,%s,%s,%s,%s,%s) RETURNING id",
                    (str(project_id), type_, stage, status, message, Jsonb(data or {})),
                )
            ).fetchone()
    except Exception as e:
        logger.warning(f"emit failed ({type_}: {message}): {e}")
        return None
    await notify(str(project_id), row[0])
    return row[0]
