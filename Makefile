up:        ## start everything
	docker compose up --build
down:
	docker compose down
reset:     ## wipe the database volume
	docker compose down -v
migrate:
	docker compose exec backend alembic upgrade head
restart-test:  ## Step 1 checkpoint: crash a graph mid-run, resume in a new process
	docker compose exec backend python -m scripts.restart_test
infra:     ## start only db + redis (run backend/worker/frontend/renderer locally)
	docker compose up -d db redis
worker:    ## local Celery worker (Windows: make worker POOL=solo)
	cd backend && uv run celery -A app.worker.celery_app worker --loglevel=INFO --concurrency=2 -Q siteforge --pool=$(or $(POOL),prefork)
ping-worker:  ## Step 1 checkpoint: round-trip a task through Redis and the worker
	cd backend && uv run python -m scripts.ping_worker
migrate-local:  ## apply Alembic migrations to the local Postgres (make infra first)
	cd backend && uv run alembic upgrade head
