import os

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://siteforge:siteforge@localhost:5432/siteforge"
)
SQLALCHEMY_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg://", 1)

# ---- Chat models: "provider:model_id" refs. These are only the DEFAULTS;
# runtime overrides in the model_overrides table always win (switch on the go).
DEFAULT_CHAT_REFS = {
    "reasoning": os.environ.get("LLM_REASONING", "nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b"),
    "fast": os.environ.get("LLM_FAST", "nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b"),
}
# Tried in order when the chosen model fails transiently / its API key is missing.
LLM_FALLBACKS = [r.strip() for r in os.environ.get("LLM_FALLBACKS", "").split(",") if r.strip()]
LLM_TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "300"))

# ---- Embeddings. Dimension is FIXED by the DB column (vector(1536)); every
# embedder must emit exactly this many dims (Gemini/OpenAI both support it).
EMBEDDING_DIM = 1536
DEFAULT_EMBEDDING_REF = os.environ.get("EMBEDDING_MODEL", "google:gemini-embedding-2")

# Browser origins allowed to call the API (comma-separated). Add your deployed frontend URL here.
CORS_ORIGINS = [
    o.strip()
    for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(
        ","
    )
    if o.strip()
]

# ---- Agent tools. LangSearch is free: https://langsearch.com/api-keys (env LANGSEARCH_API_KEY).
# Without a key the research phase is skipped and agents run exactly as before.
RESEARCH_TIMEOUT_S = float(os.environ.get("RESEARCH_TIMEOUT_S", "90"))

# ---- Redis / Celery (task queue). Postgres stays the source of truth for workflow state;
# Redis is only the broker (and, later, the live-progress pub/sub channel).
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL", REDIS_URL)
# Only used by the `ping` smoke task; real tasks ignore results (state lives in Postgres).
CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_QUEUE = os.environ.get("CELERY_QUEUE", "siteforge")
# A whole graph run (several LLM calls, retries) must finish inside these limits.
CELERY_SOFT_TIME_LIMIT_S = int(os.environ.get("CELERY_SOFT_TIME_LIMIT_S", "1800"))
CELERY_TIME_LIMIT_S = int(os.environ.get("CELERY_TIME_LIMIT_S", "2100"))
# Redis re-delivers an un-acked task after this long. It MUST exceed CELERY_TIME_LIMIT_S,
# otherwise a slow-but-healthy run gets delivered to a second worker.
CELERY_VISIBILITY_TIMEOUT_S = int(os.environ.get("CELERY_VISIBILITY_TIMEOUT_S", "3600"))
