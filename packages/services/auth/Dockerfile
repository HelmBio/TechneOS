FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace definition and packages
COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/services/auth/pyproject.toml packages/services/auth/pyproject.toml

# Copy source code
COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/services/auth/src packages/services/auth/src

# Install dependencies
RUN uv sync --frozen --no-dev --package auth-service

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "auth_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
