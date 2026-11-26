"""Celery tasks. Step 1 ships only a smoke-test task; the real pipeline task arrives in Step 2."""

import logging

from app.worker.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="worker.ping", ignore_result=False)
def ping() -> str:
    """Round-trip smoke test: API -> Redis -> worker -> Redis -> caller."""
    logger.info("worker.ping received")
    return "pong"
