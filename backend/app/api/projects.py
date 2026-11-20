import json
import logging
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from app.graph.deps import Deps, get_deps
from app.graph.service import status as get_status
from app.store.artifacts import load_latest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/projects", tags=["projects"])


class CreateProjectRequest(BaseModel):
    user_id: str = "default-user"
    brand_name: str
    prompt: str
    niche: str


def safe_serialize(obj: Any) -> Any:
    """Recursively serialize LangGraph events: Interrupts, Pydantic, UUID, datetime."""
    from langgraph.types import Interrupt

    if isinstance(obj, Interrupt):
        return safe_serialize(obj.value)
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [safe_serialize(i) for i in obj]
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, default=str)}\n\n"


async def stream_graph_events(graph, deps: Deps, project_id: str, input_data: Any):
    yield sse({"type": "init", "project_id": project_id})
    thread_id = f"proj-{project_id}"
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 100}
    try:
        async for event in graph.astream(input_data, config, stream_mode="updates"):
            # event is {node_name: state_update} OR {"__interrupt__": (Interrupt, ...)}
            if "__interrupt__" in event:
                # event["__interrupt__"] is a TUPLE/LIST of Interrupt objects
                for intr in event["__interrupt__"]:
                    payload = intr.value if hasattr(intr, "value") else intr
                    logger.info(
                        f"🛑 [SSE] interrupt raised: {payload.get('type') if isinstance(payload, dict) else payload}"
                    )
                    yield sse({"type": "interrupt", "payload": safe_serialize(payload)})
            else:
                for node, update in event.items():
                    logger.info(f"📡 [SSE] node '{node}' update")
                    yield sse({"type": "node", "node": node, "update": safe_serialize(update)})

        # Clean snapshot so the UI always ends in a consistent state
        final = await get_status(graph, deps, project_id)
        yield sse({"type": "status", "payload": safe_serialize(final)})

    except Exception as e:
        logger.error(f"❌ [SSE] stream error: {e}", exc_info=True)
        yield sse({"type": "error", "message": str(e)})


@router.post("/")
async def create_project(req: CreateProjectRequest, deps: Deps = Depends(get_deps)):
    logger.info(f"📥 POST /v1/projects/ | brand='{req.brand_name}' niche='{req.niche}'")
    try:
        pid = str(uuid.uuid4())
        async with await psycopg.AsyncConnection.connect(deps.dsn, autocommit=True) as conn:
            await conn.execute(
                "INSERT INTO projects (id, user_id, brand_name, prompt, niche, thread_id) "
                "VALUES (%s,%s,%s,%s,%s,%s)",
                (pid, req.user_id, req.brand_name, req.prompt, req.niche, f"proj-{pid}"),
            )
        input_data = {
            "project_id": pid,
            "user_id": req.user_id,
            "brand_name": req.brand_name,
            "prompt": req.prompt,
            "niche": req.niche,
            "brand_approved": False,
        }
        return StreamingResponse(
            stream_graph_events(deps.graph, deps, pid, input_data),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.error(f"❌ Error creating project: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/{project_id}/resume")
async def resume_project(project_id: str, payload: dict, deps: Deps = Depends(get_deps)):
    logger.info(f"🔄 POST /v1/projects/{project_id}/resume | action={payload.get('action')}")
    try:
        st = await get_status(deps.graph, deps, project_id)
        if not st.get("waiting_for"):
            raise HTTPException(status_code=400, detail="workflow is not waiting for input")
        return StreamingResponse(
            stream_graph_events(deps.graph, deps, project_id, Command(resume=payload)),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error resuming project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{project_id}/status")
async def get_project_status(project_id: str, deps: Deps = Depends(get_deps)):
    try:
        return await get_status(graph=deps.graph, deps=deps, project_id=project_id)
    except KeyError:
        # Use 'from None' because KeyError is expected and we don't need to chain it
        raise HTTPException(status_code=404, detail="Project not found") from None
    except Exception as e:
        logger.error(f"❌ Error getting status for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{project_id}/site")
async def get_site_document(project_id: str, version: int = 1, deps: Deps = Depends(get_deps)):
    # Note: 'version' param is kept for API compatibility.
    # load_latest fetches the most recent approved version.
    async with await psycopg.AsyncConnection.connect(deps.dsn) as conn:
        art = await load_latest(conn, project_id, "site_document")
        if not art:
            raise HTTPException(status_code=404, detail="Site document not found")
        return art.content
