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
