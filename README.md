# TechneOS

An AI-powered data and computing platform for drug discovery: manage molecular
datasets, register computational tools, execute pipelines as DAGs, run AI agents
for autonomous tasks, and track human tasks — through a web portal, REST API,
and CLI. Supports **SaaS (multi-tenant)** and **self-hosted (on-premises)**
deployment.

> **Status — services + clients + web portal + SSO + execution layer + tests.**
> This README is a *living document* that tracks what the repository actually
> contains today, and grows with each commit. Right now the repo holds the
> architecture design, a runnable local development environment with
> **Keycloak SSO** (Google + GitHub identity providers), the foundation
> Python layer (shared **core** library, **tool-runtime**, database migrations),
> the **service tier** (API gateway, eight domain microservices, built-in
> Platform Assistant), the **client tier**: the `techneos` **CLI** and the
> **management** toolkit (admin/registration + wheel publishing), the
> **web portal** (Next.js), the **execution layer** (Apache Airflow DAGs +
> pluggable compute backends), and a **test suite** (unit + integration). The
> deployment assets are introduced in a subsequent commit.

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
| `packages/portal/` | The web portal (Next.js 16 / React 19 / TypeScript / Tailwind CSS v4) — the primary UI for datasets, tools, pipelines, agents, apps, tasks, and admin; talks to the gateway REST API only |
| `packages/execution/` | The execution layer — Apache Airflow DAGs, the `ToolOperator`, status callbacks, and pluggable compute backends (Docker, AWS Batch, Slurm, human). Runs inside the Airflow containers; not a uv workspace member |
| `tests/` | Test suite — `tests/unit` (fast, mocked) and `tests/integration` (marked `integration`, need the stack up) |
| `migrations/` + `alembic.ini` | Alembic setup with a single baseline migration defining the full schema |
| `keycloak/techneos-realm.dev.json` | Keycloak realm import for local dev — `techneos` realm, API/web clients, Google + GitHub identity providers |
| `docker-compose.yml` | Local dev infrastructure (PostgreSQL, MinIO, Valkey, DevPI, Keycloak with SSO, Airflow) |
| `Makefile` | Developer command shortcuts (`make help`) |
| `pyproject.toml` | Root uv workspace (Python packages only — the web portal is a separate npm package; `packages/execution` is intentionally excluded, as it runs in the Airflow containers) |
| `.env.example` | Environment variable template |
| `AGENTS.md` | Conventions & subsystem notes for coding agents |

## Getting started

**Prerequisites:** Docker & Docker Compose, Python 3.12, Node.js 20+, and
[uv](https://docs.astral.sh/uv/getting-started/installation/).

```bash
cp .env.example .env   # defaults work for local dev
make up                # start PostgreSQL, MinIO, Valkey, DevPI, Keycloak
make install           # install the Python workspace
make migrate           # apply the database schema
make seed              # create default roles, org, team, and an admin user
make install-portal    # install the web portal's npm dependencies
make dev-all-portal    # run every backend service + the web portal (localhost:3000)
```

Or run pieces individually: `make dev-gateway` (API gateway, `:8000`),
`make dev-auth` / `dev-dataset` / … for the other services, `make dev-portal`
for just the web portal, and `make dev-cli cmd="datasets list"` for the CLI.
`make dev-all` / `make dev-stop` start/stop the whole backend via
[`bin/dev.sh`](bin/dev.sh). Run `make help` to see every target.

After `make seed`, log in with the seeded admin account (`admin@example.com` /
`changeme123`, from `packages/core/src/core/database/.techneos.example.json`)
or register a new one from the login page. To enable Google/GitHub sign-in,
see the "Authentication (Keycloak SSO)" section in [`AGENTS.md`](AGENTS.md) —
it takes a Keycloak config in `.env` plus your own OAuth app credentials.

## Testing

```bash
make test              # integrated-platform tests (top-level tests/), excludes integration
make test-unit         # integrated-platform unit tests only
make test-integration  # integration tests (requires `make up` first)
make test-cov          # integrated-platform tests with a coverage report
make test-cli          # CLI client's in-package tests
make test-management   # management client's in-package tests
make test-tool-runtime # tool-runtime's in-package tests
make test-execution    # execution layer's in-package tests
make test-portal       # web portal (Vitest) tests
make test-all          # every suite: integrated platform + in-package + portal
```

The top-level `tests/` suite covers the server-side platform (core, gateway,
the eight services). Packages shipped or run outside the platform deployment
own their tests in-package and get a dedicated target: the `cli` and
`management` client wheels, the `tool-runtime` base wheel, the `execution`
(Airflow) runtime, and the `portal` (Vitest). A package is tested at one level
only, never both.

Integration tests are marked `integration` and excluded from the default run;
they run against the live stack (a dedicated `techneos_test` database) and
require `make up`.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — full architecture design document
