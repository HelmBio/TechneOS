FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/services/notification/pyproject.toml packages/services/notification/pyproject.toml

COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/services/notification/src packages/services/notification/src

RUN uv sync --frozen --no-dev --package notification-service

EXPOSE 8006

CMD ["uv", "run", "uvicorn", "notification_service.main:app", "--host", "0.0.0.0", "--port", "8006"]
