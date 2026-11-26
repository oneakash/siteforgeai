"""Project API. Long-running work happens in Celery workers, never inside a request.

POST   /v1/projects/                  create + enqueue the first run       -> 202
POST   /v1/projects/{id}/resume       answer the pending review/question   -> 202 (409 if not waiting)
POST   /v1/projects/{id}/continue     re-enqueue after a failure/restart   -> 202 (409 if waiting)
GET    /v1/projects/{id}/status       live phase, tasks, pending question
GET    /v1/projects/{id}/site         the generated Site Document
"""

import logging
import uuid

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.graph.deps import Deps, get_deps
from app.graph.service import INTERRUPT_MODELS, pending_resume_token
from app.graph.service import status as get_status
from app.store.artifacts import load_latest
from app.store.tasks import audit, set_phase
from app.worker.tasks import run_project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    user_id: str = "default-user"
    brand_name: str
    prompt: str
    niche: str


def _accepted(project_id: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=202, content={"project_id": project_id, **extra})


async def _enqueue(deps: Deps, project_id: str, **kwargs) -> None:
    """Hand a run to Celery. If the broker is down, flag the project so /continue can retry."""
    try:
        await run_in_threadpool(
            lambda: run_project.apply_async(args=[project_id], kwargs=kwargs)
        )  # kombu publish is blocking I/O
    except Exception as e:
        logger.error(f"❌ enqueue failed for {project_id}: {e}", exc_info=True)
        async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
            await conn.execute(
                "UPDATE projects SET status='error', updated_at=now() WHERE id=%s::uuid",
                (project_id,),
            )
            await audit(conn, project_id, "system", "enqueue_failed", {"error": str(e)[:300]})
        raise HTTPException(status_code=503, detail="task queue unavailable; retry shortly") from e


@router.post("/", status_code=202)
async def create_project(req: CreateProjectRequest, deps: Deps = Depends(get_deps)):
    logger.info(f"📥 POST /v1/projects/ | brand='{req.brand_name}' niche='{req.niche}'")
    pid = str(uuid.uuid4())
    async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO projects (id, user_id, brand_name, prompt, niche, thread_id) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            (pid, req.user_id, req.brand_name, req.prompt, req.niche, f"proj-{pid}"),
        )
        await set_phase(conn, pid, "queued", "queued")
        await audit(
            conn, pid, "user", "project_created", {"brand_name": req.brand_name, "niche": req.niche}
        )
    await _enqueue(deps, pid, mode="start")
    return _accepted(pid, status="queued")


@router.post("/{project_id}/resume", status_code=202)
async def resume_project(project_id: str, payload: dict, deps: Deps = Depends(get_deps)):
    logger.info(f"🔄 POST /v1/projects/{project_id}/resume | action={payload.get('action')}")
    try:
        st = await get_status(deps.graph, deps, project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    wait = st.get("waiting_for")
    if not wait:
        raise HTTPException(status_code=409, detail="workflow is not waiting for input")
    try:  # validate BEFORE enqueueing: bad input must not reach the worker
        INTERRUPT_MODELS[wait["type"]].model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors(include_url=False)) from e
    token = await pending_resume_token(deps.graph, deps, project_id)
    async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
        await set_phase(conn, project_id, "queued", "queued")
    await _enqueue(deps, project_id, mode="resume", payload=payload, token=token)
    return _accepted(project_id, status="queued")


@router.post("/{project_id}/continue", status_code=202)
async def continue_project(project_id: str, deps: Deps = Depends(get_deps)):
    """Re-enqueue a run that stopped (worker crash, exhausted retries, broker outage)."""
    try:
        st = await get_status(deps.graph, deps, project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    if st.get("waiting_for"):
        raise HTTPException(status_code=409, detail="workflow is waiting for input; use /resume")
    await _enqueue(deps, project_id, mode="continue")
    return _accepted(project_id, status="queued")


@router.get("/{project_id}/status")
async def get_project_status(project_id: str, deps: Deps = Depends(get_deps)):
    try:
        return await get_status(graph=deps.graph, deps=deps, project_id=project_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    except Exception as e:
        logger.error(f"❌ Error getting status for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{project_id}/site")
async def get_site_document(project_id: str, version: int = 1, deps: Deps = Depends(get_deps)):
    # 'version' is kept for API compatibility; load_latest returns the newest document.
    async with await psycopg.AsyncConnection.connect(deps.dsn) as conn:
        art = await load_latest(conn, project_id, "site_document")
        if not art:
            raise HTTPException(status_code=404, detail="Site document not found")
        return art.content
