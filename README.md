# TechneOS

An AI-powered data and computing platform for drug discovery: manage molecular
datasets, register computational tools, execute pipelines as DAGs, run AI agents
for autonomous tasks, and track human tasks — through a web portal, REST API,
and CLI. Supports **SaaS (multi-tenant)** and **self-hosted (on-premises)**
deployment.

> **Status — services + clients.**
> This README is a *living document* that tracks what the repository actually
> contains today, and grows with each commit. Right now the repo holds the
> architecture design, a runnable local development environment, the foundation
> Python layer (shared **core** library, **tool-runtime**, database migrations),
> the **service tier** (API gateway, eight domain microservices, built-in
> Platform Assistant), and the **client tier**: the `techneos` **CLI** and the
> **management** toolkit (admin/registration + wheel publishing). The web portal,
> execution layer, and deployment assets are introduced in subsequent commits.

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for the full system design.
The target technology stack:

| Layer | Technologies |
|-------|-------------|
| **Backend** | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2, PydanticAI, Alembic |
| **Frontend** | Next.js 16, React 19, TypeScript, Tailwind CSS v4 |
| **CLI** | Typer, Rich, httpx |
| **Infra** | PostgreSQL 16, MinIO, Valkey, DevPI, Apache Airflow, Keycloak |
| **Tooling** | uv (monorepo), Ruff, mypy (strict), pytest |
| **Deployment** | Docker Compose, AWS CodePipeline (production) |

## What's in the repo today

| Path | Purpose |
|------|---------|
| [`docs/architecture.md`](docs/architecture.md) | Full architecture design document |
| `packages/core/` | Shared library: SQLAlchemy models, Pydantic schemas, auth, storage, cache, events, agent bridge — every service builds on it |
| `packages/tool-runtime/` | Tool execution runtime (runner + I/O contract); builds the `techneos/tool-runtime` image. Foundation package with no intra-workspace dependencies |
| `packages/gateway/` | API gateway (`:8000`) — reverse proxy, auth middleware, rate limiting, routing; the front door for the portal, CLI, and REST clients |
| `packages/services/` | The eight domain microservices: `auth` (`:8001`), `dataset` (`:8002`), `tool` (`:8003`), `pipeline` (`:8004`), `agent` (`:8005`), `notification` (`:8006`), `app` (`:8007`), `task` (`:8008`) |
| `packages/platform-assistant/` | The built-in Platform Assistant agent (PydanticAI); the agent-service depends on it |
| `packages/cli/` | The `techneos` command-line client (Typer/Rich/httpx) — talks to the platform through the gateway REST API |
| `packages/management/` | Admin/registration toolkit published as the `techneos-management` wheel: resource-removal scripts and the registration helpers used by build/publish scripts |
| `migrations/` + `alembic.ini` | Alembic setup with the squashed initial schema baseline |
| `docker-compose.yml` | Local dev infrastructure (PostgreSQL, MinIO, Valkey, DevPI, Keycloak) |
| `Makefile` | Developer command shortcuts (`make help`) |
| `pyproject.toml` | Root uv workspace (all Python packages; the web portal and execution layer are added in later commits) |
| `.env.example` | Environment variable template |
| `AGENTS.md` | Conventions & subsystem notes for coding agents |

## Getting started

**Prerequisites:** Docker & Docker Compose, Python 3.12, and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cp .env.example .env   # defaults work for local dev
make up                # start PostgreSQL, MinIO, Valkey, DevPI, Keycloak
make install           # install the Python workspace
make migrate           # apply the database schema
make dev-gateway       # run the API gateway (:8000); make dev-auth, dev-dataset, … for services
make dev-cli cmd="datasets list"   # run the techneos CLI against the gateway
```

Run `make help` to see all available targets (per-service `dev-*` runners, the
CLI, lint, format, typecheck, migration helpers, etc.). Node.js 20+ becomes a
prerequisite once the web portal is added in a later commit.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full architecture design document
