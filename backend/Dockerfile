FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# 1. Copy dependency file first for layer caching
COPY pyproject.toml ./

# 2. Install dependencies (creates .venv in /app)
# Use 'uv sync --frozen' if you have a uv.lock file, otherwise just 'uv sync'
RUN uv sync

# 3. Add the virtual environment to PATH so 'alembic' and 'uvicorn' are found
ENV PATH="/app/.venv/bin:$PATH"

# 4. Copy the rest of the application code
COPY . .

EXPOSE 8000

# 5. Run migrations and start server
# Using 'python -m' is the most robust way to ensure we run the venv packages
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"]