"""Celery wiring tests. No broker needed: tasks run eagerly in-process."""

from app.worker.celery_app import celery_app
from app.worker.tasks import ping


def test_reliability_settings():
    c = celery_app.conf
    # a killed worker must cause re-delivery, not a lost job
    assert c.task_acks_late is True
    assert c.task_reject_on_worker_lost is True
    assert c.worker_prefetch_multiplier == 1


def test_json_only_serialization():
    c = celery_app.conf
    assert c.task_serializer == "json"
    assert list(c.accept_content) == ["json"]


def test_visibility_timeout_exceeds_time_limit():
    # otherwise Redis re-delivers a healthy long run to a second worker
    vt = celery_app.conf.broker_transport_options["visibility_timeout"]
    assert vt > celery_app.conf.task_time_limit > celery_app.conf.task_soft_time_limit


def test_ping_task_is_registered_and_runs():
    assert "worker.ping" in celery_app.tasks
    assert ping.apply().get() == "pong"
