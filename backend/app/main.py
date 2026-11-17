from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import CORS_ORIGINS, DATABASE_URL
from app.api.models import router as models_router
from app.graph.checkpointer import checkpointer_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with checkpointer_pool() as saver:
        app.state.checkpointer = saver
        yield


app = FastAPI(title="SiteForge API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=CORS_ORIGINS, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)  # the Next.js app (port 3000) calls this API (port 8000) from the browser
app.include_router(models_router)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/health/db")
async def health_db():
    with psycopg.connect(DATABASE_URL) as conn:
        ext = conn.execute("SELECT extversion FROM pg_extension WHERE extname='vector'").fetchone()
        tables = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY 1"
        ).fetchall()
    return {"pgvector": ext[0] if ext else None, "tables": [t[0] for t in tables]}
