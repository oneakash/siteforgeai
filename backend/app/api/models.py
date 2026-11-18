"""Switch models at runtime. No restart; takes effect on the next LLM call."""
from typing import Literal, Optional
from uuid import UUID

import psycopg
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.agents.registry import AGENTS
from app.config import DATABASE_URL, DEFAULT_CHAT_REFS, DEFAULT_EMBEDDING_REF, LLM_FALLBACKS
from app.llm.router import ModelRef, PROVIDERS, ProviderConfigError, provider_ready

router = APIRouter(prefix="/v1/models", tags=["models"])


class OverrideIn(BaseModel):
    model_ref: str                                   # 'provider:model_id'
    purpose: Literal["chat", "embedding"] = "chat"
    project_id: Optional[UUID] = None                # omit => global
    agent: Optional[str] = None                      # omit => all agents (chat only)
    tier: Optional[Literal["reasoning", "fast"]] = None


@router.get("")
async def effective_config():
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        rows = await (await conn.execute(
            "SELECT project_id::text, agent, tier, purpose, model_ref FROM model_overrides ORDER BY purpose, project_id NULLS FIRST"
        )).fetchall()
    return {
        "defaults": {**DEFAULT_CHAT_REFS, "embedding": DEFAULT_EMBEDDING_REF},
        "fallbacks": LLM_FALLBACKS,
        "providers": {p: {"configured": bool(__import__("os").environ.get(s.env_key)), "chat": s.chat, "embeddings": s.embeddings}
                      for p, s in PROVIDERS.items()},
        "agents": sorted(AGENTS),
        "overrides": [dict(zip(("project_id", "agent", "tier", "purpose", "model_ref"), r)) for r in rows],
    }


@router.put("/overrides")
async def set_override(body: OverrideIn):
    try:
        ref = ModelRef.parse(body.model_ref)
        spec = PROVIDERS.get(ref.provider)
        if not spec:
            raise ProviderConfigError(f"unknown provider '{ref.provider}'")
        if body.purpose == "embedding" and not spec.embeddings:
            raise ProviderConfigError(f"provider '{ref.provider}' has no embedding models here")
        if not provider_ready(ref):
            raise ProviderConfigError(f"{spec.env_key} is not set on the server")
    except ProviderConfigError as e:
        raise HTTPException(400, str(e))
    if body.agent and body.agent not in AGENTS:
        raise HTTPException(400, f"unknown agent '{body.agent}'")
    if body.purpose == "embedding" and (body.agent or body.tier or body.project_id):
        raise HTTPException(400, "the embedding model is system-wide (one vector space): no project/agent/tier scope. "
                                 "After switching, POST /v1/memories/reembed to rebuild stored vectors.")
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        await conn.execute(
            "INSERT INTO model_overrides (project_id, agent, tier, purpose, model_ref) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (project_id, agent, tier, purpose) DO UPDATE SET model_ref = EXCLUDED.model_ref, updated_at = now()",
            (body.project_id, body.agent, body.tier, body.purpose, str(ref)),
        )
        if body.project_id:
            await conn.execute(
                "INSERT INTO audit_log (project_id, actor, action, payload) VALUES (%s,'user','model_override_set',%s::jsonb)",
                (body.project_id, body.model_dump_json()),
            )
    return {"ok": True, "model_ref": str(ref)}


@router.delete("/overrides")
async def clear_override(purpose: Literal["chat", "embedding"] = "chat", project_id: Optional[UUID] = None,
                         agent: Optional[str] = None, tier: Optional[Literal["reasoning", "fast"]] = None):
    async with await psycopg.AsyncConnection.connect(DATABASE_URL, autocommit=True) as conn:
        cur = await conn.execute(
            "DELETE FROM model_overrides WHERE project_id IS NOT DISTINCT FROM %s AND agent IS NOT DISTINCT FROM %s "
            "AND tier IS NOT DISTINCT FROM %s AND purpose = %s", (project_id, agent, tier, purpose))
    return {"deleted": cur.rowcount}
