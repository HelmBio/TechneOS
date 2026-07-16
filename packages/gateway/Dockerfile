FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy workspace definition and core package
COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/gateway/pyproject.toml packages/gateway/pyproject.toml

# Copy source code
COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/gateway/src packages/gateway/src

# Build the client wheel the gateway serves at /cli/simple/. Building it here
# ties the CLI customers install to the image they install it from, so the two
# cannot drift. techneos-cli is not a gateway dependency and is not installed.
COPY packages/cli packages/cli
RUN uv build packages/cli --wheel -o cli-dist && rm -rf packages/cli

# Copy alembic config and migrations
COPY alembic.ini ./
COPY migrations migrations/

# Install dependencies
RUN uv sync --frozen --no-dev --package gateway

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
