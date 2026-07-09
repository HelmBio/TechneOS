FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/services/pipeline/pyproject.toml packages/services/pipeline/pyproject.toml

COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/services/pipeline/src packages/services/pipeline/src

RUN uv sync --frozen --no-dev --package pipeline-service

EXPOSE 8004

CMD ["uv", "run", "uvicorn", "pipeline_service.main:app", "--host", "0.0.0.0", "--port", "8004"]
