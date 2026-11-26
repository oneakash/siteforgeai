"""Celery application: Redis broker, at-least-once delivery, Postgres as source of truth.

Delivery model
--------------
* ``task_acks_late`` + ``task_reject_on_worker_lost``: a task is acknowledged only AFTER it
  finishes. If the worker process is killed mid-run, the broker re-delivers it to another
  worker. Combined with the LangGraph Postgres checkpointer and the task ledger, the re-run
  continues from the last checkpoint instead of starting over.
* ``worker_prefetch_multiplier=1``: tasks are long (minutes); never let one worker hoard
  queued jobs while another sits idle.
* Results are ignored: workflow state lives in Postgres, not in the Celery result backend.
"""

from dotenv import load_dotenv

load_dotenv()  # so `celery -A ...` run from backend/ also sees the repo-root .env

from celery import Celery  # noqa: E402

from app.config import (  # noqa: E402
    CELERY_BROKER_URL,
    CELERY_QUEUE,
    CELERY_RESULT_BACKEND,
    CELERY_SOFT_TIME_LIMIT_S,
    CELERY_TIME_LIMIT_S,
    CELERY_VISIBILITY_TIMEOUT_S,
)

celery_app = Celery(
    "siteforge",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    # --- serialization: JSON only (never pickle)
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # --- routing
    task_default_queue=CELERY_QUEUE,
    # --- reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": CELERY_VISIBILITY_TIMEOUT_S},
    # --- limits
    task_soft_time_limit=CELERY_SOFT_TIME_LIMIT_S,
    task_time_limit=CELERY_TIME_LIMIT_S,
    # --- results: off by default (Postgres is the source of truth)
    task_ignore_result=True,
    result_expires=3600,
    # --- hygiene
    worker_max_tasks_per_child=100,  # recycle processes to bound memory growth
)
