FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/services/task/pyproject.toml packages/services/task/pyproject.toml

COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/services/task/src packages/services/task/src

RUN uv sync --frozen --no-dev --package task-service

EXPOSE 8008

CMD ["uv", "run", "uvicorn", "task_service.main:app", "--host", "0.0.0.0", "--port", "8008"]
