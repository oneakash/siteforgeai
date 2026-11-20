.PHONY: format lint typecheck test

format:
	isort app/ tests/
	black app/ tests/

lint:
	ruff check app/ tests/

typecheck:
	mypy app/

test:
	pytest -v

# Run everything before pushing
check-all: format lint typecheck test