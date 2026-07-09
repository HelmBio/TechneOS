FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/services/tool/pyproject.toml packages/services/tool/pyproject.toml

COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/services/tool/src packages/services/tool/src

RUN uv sync --frozen --no-dev --package tool-service

EXPOSE 8003

CMD ["uv", "run", "uvicorn", "tool_service.main:app", "--host", "0.0.0.0", "--port", "8003"]
