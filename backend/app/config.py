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