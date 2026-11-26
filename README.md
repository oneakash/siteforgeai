# SiteForge (Step 1: foundation)

    cp .env.example .env
    docker compose up --build        # db + backend (auto-migrates) + frontend + renderer
    make restart-test                # crash a graph mid-run, resume in a new process

# Ensure your database is running (you can still use docker compose just for the DB)
docker compose up db redis -d
docker compose up --build -d db redis arq_worker

# Run the backend with auto-reload
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Run the renderer
cd renderer
BACKEND_URL=http://localhost:8000 node server.js

# Run frontend
cd frontend
npm run dev

| Service  | URL                             |
|----------|---------------------------------|
| Frontend | http://localhost:3000           |
| API      | http://localhost:8000/health/db |
| Renderer | http://localhost:4000           |

Notes
- Workflow state lives only in LangGraph's Postgres checkpointer tables (created by `saver.setup()`).
- Run graphs with `durability="sync"` so a hard kill cannot lose the last checkpoint.
- Even so, keep the task-ledger guard (tasks.status) for side effects: a crash between a node's
  side effect and its checkpoint commit can still replay that node once.

## Step 2: contracts + run_agent

    cd backend && pip install -r requirements-dev.txt && pytest      # 35 tests (DB tests need Postgres up)

- `app/contracts/`  Pydantic models for every agent boundary (+ `ARTIFACT_MODELS` kind->model map)
- `app/agents/registry.py`  one `AgentSpec` per agent; cross-artifact validators live here
- `app/agents/runner.py`  `run_agent()`: envelope -> LLM -> validate -> corrective re-prompt (max 2) -> typed result
- `app/agents/execute.py`  `execute_task()`: skip if the task already has an artifact, else run + persist
- `app/store/artifacts.py`  idempotent versioned artifact writes (task_id UNIQUE)
- `FakeLLM` (`app/agents/llm.py`) drives all tests; the OpenAI adapter is only exercised in prod.

## Switching models on the go

Refs are `provider:model_id`: `nvidia:` (build.nvidia.com), `groq:`, `google:` (and optionally `openai:`; no OpenAI key is needed or used by default).
Check your real models/keys: `docker compose exec backend python -m scripts.check_models`

    # defaults come from .env (LLM_REASONING / LLM_FAST / LLM_FALLBACKS / EMBEDDING_MODEL)
    # switch at runtime, no restart (global, per project, per agent, or per tier):
    curl -X PUT localhost:8000/v1/models/overrides -H 'content-type: application/json' \
      -d '{"model_ref":"nvidia:nvidia/nemotron-3.5-super-vl-120b-a12b","agent":"brand_guideline"}'
    curl localhost:8000/v1/models            # effective config + which providers have keys
    curl -X DELETE 'localhost:8000/v1/models/overrides?agent=brand_guideline'

Precedence: project > global; then agent > tier > general; then the .env default.
Embedding switch: old vectors are ignored by search until `reembed_stale()` rebuilds them.

## Step 3: the orchestration graph

    cd backend && pytest                                   # 59 tests, real Postgres checkpointer
    python -m scripts.recovery_demo start --crash-on AudienceReport    # dies with exit 137
    python -m scripts.recovery_demo continue --project <id>            # resumes, no finished work repeated

- `app/graph/root.py`   root StateGraph: plan -> scheduler(route) -> research SUBGRAPH / workers (Send) -> collect -> ...
- `app/graph/nodes.py`  node logic (idempotent; ledger-guarded; interrupt() only after read-only work)
- `app/graph/service.py` start_project / resume / continue_run / status  (FastAPI wraps these in Step 7)
- `app/store/tasks.py`  task ledger, audit trail, phase
- `app/demo/`           DemoLLM + sample payloads: the whole graph runs with no API key

## Step 4: memory

    docker compose restart backend          # applies migration 0003
    docker compose exec backend pytest -q   # 81 tests

- **Facts vs. logs.** A *fact* has a `topic_key` (e.g. `brand.palette`); at most ONE active version exists (DB-enforced
  partial unique index) and a change supersedes the old row (`superseded_by` chain kept). A *log entry* (decisions) has
  no topic and is deduplicated by hash + cosine >= 0.92. Drafts are never memory; only the APPROVED brand is.
- **Scopes.** `user` (follows the user to new projects, `POST /v1/users/{id}/preferences`), `project`, `session` (thread).
- **Recall.** Per-agent profile (`app/memory/profiles.py`): *pinned* topics (always, no embeddings needed) + semantic top-k
  restricted to the active embedding model; compressed to a budget before it reaches the prompt.
- **Embedding model is system-wide.** After switching it: `POST /v1/memories/reembed`.
- **Never blocks the workflow.** If embeddings are down, text is stored, pinned recall still works, `reembed` repairs later.
- Inspect: `GET /v1/projects/{id}/memories?history=true`, `GET /v1/projects/{id}/memories/search?q=...`

## Step 5: task queue (Celery + Redis)

Workflow state stays in Postgres (LangGraph checkpointer + task ledger). Redis is only the broker.
Tasks use `acks_late` + `reject_on_worker_lost`, so a killed worker's job is re-delivered and
resumes from the last checkpoint.

```
uv lock                      # in backend/: refresh uv.lock after the arq -> celery change
make infra                   # db + redis in Docker
make worker                  # Celery worker (Windows: make worker POOL=solo)
make ping-worker             # PASS = API -> Redis -> worker -> Redis round trip works
curl localhost:8000/health/redis ; curl localhost:8000/health/worker
```

- `app/worker/celery_app.py` Celery config (JSON only, results ignored, time limits, visibility timeout)
- `app/worker/tasks.py` tasks (`worker.ping` now; the graph-run task lands in the next step)
- `visibility_timeout` must stay larger than `CELERY_TIME_LIMIT_S`, or a long healthy run is re-delivered.

