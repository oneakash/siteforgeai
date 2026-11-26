"""Celery tasks."""

import asyncio
import logging

import psycopg
from celery.exceptions import SoftTimeLimitExceeded

from app.config import DATABASE_URL
from app.graph import service
from app.graph.runtime import graph_runtime
from app.store.locks import project_lock
from app.store.tasks import audit
from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


class RunInProgress(Exception):
    """Another worker holds this project's run lock; retry shortly."""


@celery_app.task(name="worker.ping", ignore_result=False)
def ping() -> str:
    """Round-trip smoke test: API -> Redis -> worker -> Redis -> caller."""
    logger.info("worker.ping received")
    return "pong"


async def _run(project_id: str, mode: str, payload: dict | None, token: str | None) -> dict:
    async with project_lock(DATABASE_URL, project_id) as acquired:
        if not acquired:
            raise RunInProgress(project_id)
        async with graph_runtime() as rt:
            return await service.run_job(
                rt.graph, rt.deps, project_id, mode=mode, payload=payload, token=token
            )


async def _record_failure(project_id: str, action: str, error: str) -> None:
    """Leave a trail + flag the project; the LangGraph checkpoint is untouched, so POST
    /v1/projects/{id}/continue can pick the run up from where it stopped."""
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await audit(conn, project_id, "system", action, {"error": error[:500]})
        await conn.execute(
            "UPDATE projects SET status='error', updated_at=now() WHERE id=%s::uuid", (project_id,)
        )


@celery_app.task(
    name="worker.run_project",
    bind=True,
    max_retries=12,
    autoretry_for=(psycopg.OperationalError, RunInProgress),
    retry_backoff=5,
    retry_backoff_max=60,
    retry_jitter=True,
)
def run_project(
    self,
    project_id: str,
    mode: str = "continue",  # start | resume | continue
    payload: dict | None = None,
    token: str | None = None,
) -> str:
    """Run (or resume) a project's workflow until it finishes or needs the user.

    Safe to deliver twice: run_job() derives what to do from the checkpoint, and the project
    lock serializes concurrent deliveries.
    """
    logger.info(f"run_project {project_id} mode={mode} attempt={self.request.retries}")
    try:
        out = asyncio.run(_run(project_id, mode, payload, token))
    except (psycopg.OperationalError, RunInProgress):
        raise  # autoretry_for handles these
    except SoftTimeLimitExceeded:
        asyncio.run(_record_failure(project_id, "run_timeout", "soft time limit exceeded"))
        return "timeout"
    except Exception as e:
        logger.exception(f"run_project {project_id} failed")
        asyncio.run(_record_failure(project_id, "worker_error", f"{type(e).__name__}: {e}"))
        raise
    return str((out or {}).get("phase"))
