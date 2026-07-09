FROM python:3.12-slim

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# ─────────────────────────────────────────────────────────────────────────────
# PACKAGE INSTALL POLICY
#
# Neither catalog AGENT packages (catalog/agents/<slug>/) nor catalog TOOL
# packages that contribute Platform Assistant inline tools are baked into
# this image any more. The agent-service reads package coordinates from the
# DB at startup and `pip install`s each from the configured Python package
# index (DevPI locally, CodeArtifact in prod) before enumerating entry
# points. See:
#   packages/services/agent/src/agent_service/main.py
#   _install_registered_agent_packages()
#   _install_registered_tool_packages()
#
# This image therefore needs `pip` available at runtime, which is true by
# default in the python:3.12-slim base. No additional install step is needed.
# ─────────────────────────────────────────────────────────────────────────────

COPY pyproject.toml ./
COPY uv.lock ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY packages/tool-runtime/pyproject.toml packages/tool-runtime/pyproject.toml
COPY packages/platform-assistant/pyproject.toml packages/platform-assistant/pyproject.toml
COPY packages/services/agent/pyproject.toml packages/services/agent/pyproject.toml

COPY packages/core/src packages/core/src
COPY packages/tool-runtime/src packages/tool-runtime/src
COPY packages/platform-assistant/src packages/platform-assistant/src
COPY packages/services/agent/src packages/services/agent/src

RUN uv sync --frozen --no-dev --package agent-service

EXPOSE 8005

CMD ["uv", "run", "uvicorn", "agent_service.main:app", "--host", "0.0.0.0", "--port", "8005"]
