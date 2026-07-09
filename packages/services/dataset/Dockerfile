FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/services/dataset/pyproject.toml packages/services/dataset/pyproject.toml

COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/services/dataset/src packages/services/dataset/src

RUN uv sync --frozen --no-dev --package dataset-service

EXPOSE 8002

CMD ["uv", "run", "uvicorn", "dataset_service.main:app", "--host", "0.0.0.0", "--port", "8002"]
