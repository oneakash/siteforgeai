# SiteForge AI

**Describe a business, get a website.** SiteForge AI is a multi-agent system that takes a brand name, a niche and a short prompt, researches the market, drafts a brand guideline, waits for **your approval**, and then generates a complete multi-page website that you can preview live in the browser.

Every step is durable: the workflow state is checkpointed in Postgres, so a crashed worker or a restarted server resumes exactly where it stopped, without repeating finished work.

---

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Architecture](#architecture)
- [Quick start (Docker)](#quick-start-docker)
- [Local development](#local-development)
- [Configuration](#configuration)
- [Using the app](#using-the-app)
- [API reference](#api-reference)
- [Switching models at runtime](#switching-models-at-runtime)
- [Memory](#memory)
- [Project structure](#project-structure)
- [Testing and code quality](#testing-and-code-quality)
- [Troubleshooting](#troubleshooting)
- [Deployment notes](#deployment-notes)
- [Current limitations](#current-limitations)

---

## Features

- **Multi-agent pipeline** built on [LangGraph](https://github.com/langchain-ai/langgraph): manager/planner, four parallel research agents, brand guideline, wireframe and per-page website generation.
- **Human-in-the-loop brand review.** The graph pauses at an interrupt; you approve or send feedback, and a triage step re-runs only what the feedback affects.
- **Typed contracts everywhere.** Agents exchange validated Pydantic artifacts, never raw chat history. Invalid output triggers an automatic corrective re-prompt (max 2).
- **Crash-safe and resumable.** LangGraph Postgres checkpointer plus a task ledger and an idempotent artifact store.
- **Background execution.** Runs happen in a Celery worker (Redis broker); the API returns `202` immediately.
- **Live progress.** Server-Sent Events stream stage changes to the UI's "Live Activity" feed, with replay on reconnect.
- **Provider-agnostic models.** NVIDIA, Groq and Google Gemini out of the box, with fallbacks and **runtime model overrides** (global, per project, per agent or per tier) without a restart.
- **Long-term memory.** Versioned facts and decision logs with pgvector semantic recall (user, project and session scopes).
- **Safe, fast rendering.** Sections are typed JSON; a small Node renderer turns them into Tailwind HTML and serves previews with a strict CSP.
- **Works without API keys** for plumbing tests, using a built-in fake LLM.

## How it works

```mermaid
flowchart TD
    A[User: brand, niche, prompt] --> B[Plan<br/>manager agent]
    B --> C{{Research fan-out<br/>in parallel}}
    C --> C1[Niche analysis]
    C --> C2[Audience research]
    C --> C3[Competitor analysis]
    C --> C4[SEO analysis]
    C1 & C2 & C3 & C4 --> D[Consolidate<br/>research digest]
    D --> E[Brand guideline]
    E --> F{{Human review<br/>interrupt}}
    F -- approve --> G[Wireframe]
    F -- revise + feedback --> T[Triage feedback]
    T -- may ask --> Q{{Clarification<br/>interrupt}}
    Q --> T
    T -- re-run only what changed --> E
    G --> H{{Page generation<br/>in parallel}}
    H --> H1[Home]
    H --> H2[About]
    H --> H3[Contact]
    H1 & H2 & H3 --> I[Assemble site document]
    I --> J[Published: live preview]
```

The project moves through these phases, which the UI shows in its header:
`queued` → `planning` → `researching` → `generating_brand` → `waiting_for_approval` → `wireframing` → `generating_site` → `published`.

Research agents can use web search via [LangSearch](https://docs.langsearch.com/api) (free tier). Without a key, the research phase is skipped and agents fall back to model knowledge.

## Architecture

```mermaid
flowchart LR
    UI[Next.js frontend<br/>:3000] -- REST + SSE --> API[FastAPI backend<br/>:8000]
    UI -- iframe preview --> R[Renderer<br/>Node :4000]
    R -- fetch site document --> API
    API -- enqueue --> RD[(Redis<br/>broker + pub/sub)]
    RD --> W[Celery worker<br/>LangGraph runs]
    W --> PG[(Postgres + pgvector<br/>checkpoints, artifacts,<br/>tasks, memory, events)]
    API --> PG
    W --> LLM[LLM providers<br/>NVIDIA / Groq / Gemini]
```

| Service | Tech | Port | Role |
|---|---|---|---|
| `frontend` | Next.js 16, React 19, Tailwind 4 | 3000 | Onboarding form, task list, live activity, review card, preview iframe |
| `backend` | FastAPI, LangGraph, SQLAlchemy/Alembic, psycopg 3 | 8000 | REST API, SSE event stream, model/memory endpoints |
| `worker` | Celery (Redis broker) | n/a | Executes the graph outside the request cycle |
| `renderer` | Node 20+, Tailwind CLI | 4000 | Renders the stored site document into HTML pages |
| `db` | Postgres 16 + pgvector | 5432 | Source of truth for all state |
| `redis` | Redis 7 | 6379 | Celery broker and live-event wake-ups only |

Design notes worth knowing:

- **Postgres is the source of truth.** Redis only carries jobs and wakes SSE streams; if Redis is down, streams fall back to polling.
- **Workers are safe to kill.** Tasks use `acks_late` and `reject_on_worker_lost`, so a killed worker's job is re-delivered and continues from the last checkpoint. A Postgres advisory lock keeps two workers off the same project.
- **Agents never emit HTML.** Pages are typed JSON sections validated by `backend/app/contracts/section_rules.py`; the renderer owns all markup and classes.

## Quick start (Docker)

**Requirements:** Docker with Compose.

```bash
cp .env.example .env
# edit .env and add at least one LLM key (GOOGLE_API_KEY is the quickest, see Configuration)
docker compose up --build
```

This starts Postgres, Redis, the backend (migrations run automatically), the Celery worker, the frontend and the renderer.

| What | URL |
|---|---|
| App | http://localhost:3000 |
| API docs (Swagger) | http://localhost:8000/docs |
| DB health | http://localhost:8000/health/db |
| Renderer health | http://localhost:4000/healthz |

Useful commands:

```bash
make down      # stop everything
make reset     # stop and wipe the database volume
make migrate   # apply migrations inside the backend container
```

## Local development

Run the infrastructure in Docker and the apps on your machine for fast reloads.

**Requirements:** Python 3.12+, [uv](https://docs.astral.sh/uv/), Node 20+, Docker.

Use one terminal per step, starting from the repository root.

```bash
# 1. Postgres + Redis
cp .env.example .env          # then add your API key(s)
make infra

# 2. Database migrations (run again after pulling new migrations)
make migrate-local

# 3. Backend API (auto-reload)
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 4. Celery worker (new terminal, from the repo root)
make worker                    # Windows: make worker POOL=solo

# 5. Renderer (new terminal)
cd renderer
npm install
BACKEND_URL=http://localhost:8000 npm run dev
# editing renderer/lib/*.js classes? run `npm run dev:css` in another terminal

# 6. Frontend (new terminal)
cd frontend
npm install
npm run dev
```

Verify the chain end to end:

```bash
make ping-worker                    # PASS = API -> Redis -> worker -> Redis round trip
curl localhost:8000/health/redis
curl localhost:8000/health/worker
docker compose exec backend python -m scripts.check_models   # real calls to your configured models (Docker setup)
# or, for a local backend:  cd backend && uv run python -m scripts.check_models
```

## Configuration

Copy `.env.example` to `.env`. The backend and worker load it automatically.

### LLM providers

Set **at least one** key. With no key, the backend starts with a fake LLM that only returns a stub plan, so no real site is generated.

| Variable | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini chat and embeddings (the default `.env.example` models use this) |
| `NVIDIA_API_KEY` | [build.nvidia.com](https://build.nvidia.com) hosted models |
| `GROQ_API_KEY` | Groq-hosted models |
| `LLM_REASONING` / `LLM_FAST` | Default chat models for each tier, as `provider:model_id` |
| `LLM_FALLBACKS` | Comma-separated refs tried in order if a model fails transiently or its key is missing |
| `EMBEDDING_MODEL` | Embedding model ref. Output must be 1536-dimensional (matches `vector(1536)`) |
| `LLM_TIMEOUT_S` | Per-call timeout in seconds (default `300`) |

Model refs look like `provider:model_id`, for example `google:gemini-3.6-flash` or `groq:openai/gpt-oss-120b`.

### Infrastructure

| Variable | Default | Notes |
|---|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `siteforge` | Used by the `db` container |
| `DATABASE_URL` | `postgresql://siteforge:siteforge@localhost:5432/siteforge` | Compose overrides the host to `db` for containers |
| `REDIS_URL` | `redis://localhost:6379/0` | Compose overrides the host to `redis` for containers |
| `CELERY_QUEUE` | `siteforge` | |
| `CELERY_SOFT_TIME_LIMIT_S` / `CELERY_TIME_LIMIT_S` | `1800` / `2100` | A whole graph run must finish within these |
| `CELERY_VISIBILITY_TIMEOUT_S` | `3600` | **Must be larger than** `CELERY_TIME_LIMIT_S`, or healthy long runs get re-delivered |
| `CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Browser origins allowed to call the API |

### Research

| Variable | Default | Notes |
|---|---|---|
| `LANGSEARCH_API_KEY` | empty | Optional web search for research agents ([free tier](https://docs.langsearch.com/api)). If empty, research falls back to model knowledge |
| `RESEARCH_TIMEOUT_S` | `90` | Research phase timeout |

### Frontend and renderer

| Variable | Service | Default | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | frontend | `http://localhost:8000` | Baked in at build time |
| `BACKEND_URL` | renderer | `http://backend:8000` | Set to `http://localhost:8000` for local runs |
| `FRONTEND_ORIGIN` | renderer | `http://localhost:3000` | Allowed `frame-ancestors` in the CSP (comma-separated) |
| `PORT` | renderer | `4000` | |

## Using the app

1. Open http://localhost:3000 and fill in **Brand / Website Name**, **Business Niche** and **What do you want to build?**, then click **Generate Website**.
2. Watch the **Execution Plan** and **Live Activity** panels while the agents research and draft the brand guideline.
3. When the status becomes `waiting for approval`, the **Brand Review** card appears. Click **Approve**, or type feedback (for example, "Make the primary color dark green") and click **Revise**.
4. After approval the wireframe and pages are generated, and the site appears in the **Live Preview** pane.

You can also drive everything from the API:

```bash
# create a project (returns 202 + project_id)
curl -s -X POST localhost:8000/v1/projects/ -H 'content-type: application/json' \
  -d '{"brand_name":"Aurum","niche":"Travel","prompt":"Luxury travel agency"}'

# poll status (phase, tasks, and what the workflow is waiting for)
curl -s localhost:8000/v1/projects/<id>/status

# watch live events (add ?after=<event id> to replay)
curl -N localhost:8000/v1/projects/<id>/events

# approve the brand guideline
curl -s -X POST localhost:8000/v1/projects/<id>/resume -H 'content-type: application/json' \
  -d '{"action":"approve"}'

# or request changes
curl -s -X POST localhost:8000/v1/projects/<id>/resume -H 'content-type: application/json' \
  -d '{"action":"revise","feedback":"Warmer colors, more playful tone"}'

# preview the rendered site: open this URL in your browser
#   http://localhost:4000/preview/<id>/v1
```

## API reference

Interactive docs are at `/docs` when the backend is running.

| Method | Path | Description |
|---|---|---|
| `POST` | `/v1/projects/` | Create a project and enqueue the run (`202`) |
| `GET` | `/v1/projects/{id}/status` | Phase, task list, and the pending question (`waiting_for`) |
| `POST` | `/v1/projects/{id}/resume` | Answer a pending question. `409` if nothing is pending, `422` for an invalid payload |
| `POST` | `/v1/projects/{id}/continue` | Re-enqueue a run that stopped (worker crash, exhausted retries, broker outage) |
| `GET` | `/v1/projects/{id}/events` | Server-Sent Events stream (supports `?after=` and `Last-Event-ID`) |
| `GET` | `/v1/projects/{id}/site` | The generated site document (JSON) |
| `GET` | `/v1/models` | Effective model config and which providers have keys |
| `PUT` | `/v1/models/overrides` | Set a model override |
| `DELETE` | `/v1/models/overrides` | Remove an override |
| `GET` | `/v1/projects/{id}/memories` | List memories (`?history=true` for superseded versions) |
| `GET` | `/v1/projects/{id}/memories/search?q=` | Semantic memory search |
| `POST` | `/v1/users/{user_id}/preferences` | Store a user-scoped preference |
| `POST` | `/v1/memories/reembed` | Rebuild embeddings after changing the embedding model |
| `GET` | `/health`, `/health/db`, `/health/redis`, `/health/worker` | Health checks |

The workflow can pause for three kinds of input: `brand_review`, `clarification` and `task_failed`. `GET .../status` tells you which one is pending.

## Switching models at runtime

Models are resolved on **every call**, so a switch takes effect on the next LLM call, even for a paused or recovering workflow.

```bash
# use a different model for one agent
curl -X PUT localhost:8000/v1/models/overrides -H 'content-type: application/json' \
  -d '{"model_ref":"groq:openai/gpt-oss-120b","agent":"brand_guideline"}'

curl localhost:8000/v1/models                                   # effective config
curl -X DELETE 'localhost:8000/v1/models/overrides?agent=brand_guideline'
```

Overrides can be scoped by `project_id`, `agent` and `tier` (`reasoning` or `fast`). Precedence: **project > global**, then **agent > tier > general**, then the `.env` default.

After switching the **embedding** model, run `POST /v1/memories/reembed`; old vectors are ignored by search until then.

## Memory

- **Facts vs. logs.** A *fact* has a `topic_key` (for example `brand.palette`). At most one active version exists (enforced by a partial unique index), and a change supersedes the old row while keeping the chain. A *log entry* (such as a decision) has no topic and is deduplicated by hash and cosine similarity (>= 0.92).
- **Only approved work becomes memory.** Drafts are never stored; the approved brand is.
- **Scopes:** `user` (follows the user across projects), `project` and `session`.
- **Recall.** Each agent has a profile of *pinned* topics (always included) plus semantic top-k, restricted to the active embedding model and compressed to a budget before reaching the prompt.
- **Never blocks the workflow.** If embeddings are down, text is still stored and pinned recall works; `reembed` repairs it later.

## Project structure

```
.
├── docker-compose.yml        # db, redis, backend, worker, frontend, renderer
├── Makefile                  # up / down / infra / worker / migrate-local / ...
├── .env.example
├── backend/
│   ├── alembic/              # migrations (initial, model overrides, memory lifecycle, run events)
│   ├── app/
│   │   ├── agents/           # agent registry, run_agent(), tool loop, execute_task()
│   │   ├── api/              # FastAPI routers: projects, events, models, memory, health
│   │   ├── contracts/        # Pydantic models for every agent boundary + section rules
│   │   ├── graph/            # root StateGraph, nodes, service (start/resume/continue), runtime
│   │   ├── llm/              # model router (overrides + fallbacks), embeddings
│   │   ├── memory/           # memory service, store, recall profiles
│   │   ├── store/            # artifact store, task ledger, advisory locks
│   │   ├── tools/            # LangSearch web search
│   │   ├── worker/           # Celery app + tasks
│   │   └── demo/             # DemoLLM + sample payloads (no API key needed)
│   ├── scripts/              # check_models, ping_worker, restart_test, recovery_demo
│   └── tests/
├── frontend/                 # Next.js app (app/page.tsx, useProjectEvents.ts)
└── renderer/                 # Node server + Tailwind (lib/sections.js, lib/page.js)
```

**Agents.** Implemented: `niche_analysis`, `audience_research`, `competitor_analysis`, `seo_analysis`, `brand_guideline`, `wireframe` and `website_generation` (one task per page: home, about, contact). The `content`, `design`, `image` and `qa` agents exist in the contracts but are not wired into the pipeline yet.

**Section types** the renderer supports: `hero`, `features`, `services`, `process_steps`, `team`, `catalog`, `pricing`, `faq`, `testimonials`, `stats`, `gallery`, `about`, `rich_text`, `cta_banner`, `contact_form`, `blog_list` and `map_location`.

## Testing and code quality

```bash
# Backend (DB tests need Postgres: run `make infra` first)
cd backend
uv sync
uv run pytest -q

# Everything before pushing: isort, black, ruff, mypy, pytest
make check-all

# Renderer (no network or backend needed)
cd renderer && npm test
```

The backend suite uses a scripted `FakeLLM`, so no API keys are required. The renderer tests check escaping, link handling, CSP, and that every emitted Tailwind class is a real utility.

Crash-recovery demos:

```bash
make restart-test                                                  # crash a graph mid-run, resume in a new process
cd backend
uv run python -m scripts.recovery_demo start --crash-on AudienceReport   # dies with exit 137
uv run python -m scripts.recovery_demo continue --project <id>           # resumes, no finished work repeated
```

## Troubleshooting

**`Bind for 0.0.0.0:5432` / `6379 failed: port is already allocated`**
Another container or a local service is using the port. Find it with `docker ps --format "table {{.Names}}\t{{.Ports}}"`, or `sudo lsof -i :5432`. Stop it, or change the host side of the mapping in `docker-compose.yml` (for example `"5433:5432"`) and update `DATABASE_URL` / `REDIS_URL` in `.env`. Containers still reach each other on the internal ports.

**Worker fails with `RuntimeError: Event loop is closed` after you approve the brand**
Each Celery task runs in its own `asyncio.run(...)` loop, but a cached HTTP client from a previous task can keep connections bound to the closed loop. Make each run use a fresh process by setting `worker_max_tasks_per_child=1` in `backend/app/worker/celery_app.py`, restart the worker, then resume the stuck project with `POST /v1/projects/{id}/continue`.

**Backend prints "No LLM API keys found... Using FakeLLM"**
No provider key is set in `.env`. Add `GOOGLE_API_KEY`, `NVIDIA_API_KEY` or `GROQ_API_KEY` and restart the backend **and** the worker.

**A project is stuck in `error`**
Check the worker logs, fix the cause, then call `POST /v1/projects/{id}/continue`. The LangGraph checkpoint is untouched, so the run picks up where it stopped.

**`make worker` hangs or crashes on Windows**
Use the solo pool: `make worker POOL=solo`.

**Preview iframe stays blank**
Check that the renderer is running on port 4000 and that `BACKEND_URL` points at the API. If you changed the frontend origin, add it to the renderer's `FRONTEND_ORIGIN`, which controls the CSP `frame-ancestors`.

## Deployment notes

- The **frontend** deploys to Vercel (set the root directory to `frontend`). Set `NEXT_PUBLIC_API_URL` to your backend's public HTTPS URL.
- The **backend, worker and renderer** need long-running processes (SSE streams, runs of up to 30 minutes, a Node HTTP server), so host them on Railway, Render, Fly.io or a VPS rather than serverless functions. Use managed Postgres with the `pgvector` extension and a normal Redis.
- Set `CORS_ORIGINS` on the backend to your frontend's URL, and `FRONTEND_ORIGIN` on the renderer for the CSP.
- Remove `--reload` and the bind-mounted source volumes from production commands.
- The preview iframe URL in `frontend/app/page.tsx` is currently hardcoded to `http://localhost:4000`. Move it to an environment variable (for example `NEXT_PUBLIC_RENDERER_URL`) before deploying.

## Current limitations

- The UI only renders the `brand_review` prompt. `clarification` and `task_failed` prompts can be answered through `POST /v1/projects/{id}/resume`, but have no UI yet.
- Generated sites are three pages (home, about, contact) with image placeholders rather than generated images.
- No authentication: projects are keyed by a default user id.
