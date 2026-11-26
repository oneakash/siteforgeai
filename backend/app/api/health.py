"""Infrastructure health endpoints for the task queue."""

import redis.asyncio as aioredis
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.config import REDIS_URL
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/redis")
async def health_redis():
    client = aioredis.from_url(REDIS_URL)
    try:
        await client.ping()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"redis unreachable: {e}") from e
    finally:
        await client.aclose()
    return {"redis": "ok"}


@router.get("/worker")
async def health_worker():
    """200 only if at least one Celery worker answers a broadcast ping."""
    replies = await run_in_threadpool(lambda: celery_app.control.ping(timeout=1.0))
    if not replies:
        raise HTTPException(status_code=503, detail="no celery worker responded")
    return {"workers": sorted(name for reply in replies for name in reply)}
