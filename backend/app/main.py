import logging
import sys
from contextlib import asynccontextmanager

import psycopg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.events import router as events_router
from app.api.health import router as health_router
from app.api.memory import router as memory_router
from app.api.models import router as models_router
from app.api.projects import router as projects_router
from app.config import CORS_ORIGINS, DATABASE_URL
from app.graph.runtime import graph_runtime
from dotenv import load_dotenv
   
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
# Suppress noisy third-party logs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger = logging.getLogger("siteforge.main")
    logger.info("🚀 Starting SiteForge API...")
    async with graph_runtime() as rt:
        app.state.checkpointer = rt.saver
        app.state.memory = rt.memory
        app.state.graph = rt.graph
        logger.info("✅ LangGraph compiled and ready.")
        yield
    logger.info("🛑 Shutting down SiteForge API...")


app = FastAPI(title="SiteForge API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(health_router)
app.include_router(events_router)
app.include_router(projects_router)
app.include_router(models_router)
app.include_router(memory_router)


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
