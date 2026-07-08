# TechneOS

An AI-powered data and computing platform for drug discovery: manage molecular
datasets, register computational tools, execute pipelines as DAGs, run AI agents
for autonomous tasks, and track human tasks — through a web portal, REST API,
and CLI. Supports **SaaS (multi-tenant)** and **self-hosted (on-premises)**
deployment.

> **Status — initial scaffold.**
> This README is a *living document* that tracks what the repository actually
> contains today, and grows with each commit. Right now the repo holds the
> architecture design and a runnable local development environment. The
> application code (shared library, API gateway, domain services, CLI, web
> portal, and execution layer) and the deployment assets are introduced in
> subsequent commits.

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
| `docker-compose.yml` | Local dev infrastructure (PostgreSQL, MinIO, Valkey, DevPI, Keycloak) |
| `Makefile` | Developer command shortcuts (`make help`) |
| `pyproject.toml` | Root uv workspace (members are added as packages land) |
| `.env.example` | Environment variable template |
| `AGENTS.md` | Conventions & subsystem notes for coding agents |

## Getting started

**Prerequisite:** Docker & Docker Compose.

```bash
cp .env.example .env   # defaults work for local dev
make up                # start PostgreSQL, MinIO, Valkey, DevPI, Keycloak
make ps                # check service status
make down              # stop everything
```

Run `make help` to see all available targets. Python 3.12 + [uv](https://docs.astral.sh/uv/getting-started/installation/)
and Node.js 20+ become prerequisites once the application code and web portal
are added in later commits.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full architecture design document
