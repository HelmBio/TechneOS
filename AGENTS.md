# AGENTS.md

Single source of truth for all coding agents (Claude Code, opencode, Codex,
Cursor, …) working on this codebase. **Part 1 — Working Agreement** covers
safety rules, build/test/deploy, layout, and conventions. **Part 2 — Subsystem
Notes & Gotchas** captures per-feature implementation details.

> **This is a living document — keep it current.** It describes the repository
> as it stands *today*, not the final design. When a commit adds a package,
> command, convention, or subsystem, update the relevant section in the same
> commit. Today the repo contains the architecture design, a local Docker
> development stack, the foundation Python layer (shared **core** library,
> **tool-runtime**, Alembic **migrations**), the **service tier** (API gateway,
> eight domain microservices, Platform Assistant), and the **client tier**: the
> `techneos` CLI and the `management` toolkit. There is no web portal, execution
> layer, or test suite yet — those land in subsequent commits, and the rules
> below that reference them take effect as they arrive.

---

# Part 1 — Working Agreement

## CRITICAL: Database Safety Rules

**NEVER perform Create, Update, or Delete operations against the production database without explicit user permission.** This includes:

- Running tests that connect to the production database (`techneos`)
- Running seed scripts or migrations against production
- Writing integration tests that use the production database
- Any code that could modify, truncate, or drop production tables

Once the test suite lands, all tests MUST use the `techneos_test` database (never the primary `techneos` database), integration tests must be marked `@pytest.mark.integration`, and they must be excluded from the default test run. *(No test suite exists in the repo yet.)*

If you need to run anything against production data, **ask the user first**.

**NEVER reset a user's password by directly updating `hashed_password` in the database.** Use the `PUT /admin/users/{user_id}/reset-password` API endpoint instead (requires `platform_admin` role). Direct DB password mutations bypass audit logging and password policy validation.

## CRITICAL: Git Commit Policy

**NEVER automatically commit changes.** Always wait for the user to explicitly ask you to commit. Stage and review changes, but do not run `git commit` unless instructed.

## Build & Run

The Makefile targets available today (run `make help` for the list):

```bash
make up         # start the local Docker infra (Postgres, MinIO, Valkey, DevPI, Keycloak)
make install    # install the uv workspace (core, tool-runtime)
make migrate    # apply Alembic migrations (make migrate-new / migrate-down also available)
make lint       # ruff check
make format     # ruff format + autofix
make typecheck  # mypy packages/
make ps         # show running services
make logs       # tail service logs
make down       # stop services (down-v also removes volumes)
make clean      # remove build artifacts and caches
```

Run a backend in dev mode with `make dev-gateway` (the API gateway on `:8000`) or
`make dev-auth` / `dev-dataset` / `dev-tool` / `dev-pipeline` / `dev-agent` /
`dev-notification` / `dev-app` for the individual services. Test and web-portal
targets are added as the corresponding code lands.

## Coding Conventions

- **Python 3.12+** -- use modern syntax (type unions with `|`, `match` statements, etc.)
- **Type annotations** -- all functions must have full type annotations. mypy strict mode is enforced.
- **Ruff** -- linter and formatter. Line length: 100. Target: py312. Key rules: E, W, F, I (isort), N, UP, B, SIM, T20, RUF.
- **No print()** in library/service code (T20 rule). Narrow exceptions (CLI output, seed scripts, service startup/shutdown, dev-visible event logging) are declared as they are added, via `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml`.
- **Pydantic v2** for all schemas and settings.
- **SQLAlchemy 2.0** async style with `AsyncSession`.
- **FastAPI** for all HTTP services with dependency injection (`Depends()`).
- **Async-first** -- use `async def` for all route handlers and database operations.

# Part 2 — Subsystem Notes & Gotchas

## Core library & database migrations

`packages/core` is the shared foundation every service depends on: SQLAlchemy
2.0 (async) models, Pydantic v2 schemas and settings, auth, object storage,
cache, the event bus, and the agent bridge. It depends only on
`packages/tool-runtime` (the tool execution runtime + I/O contract), which has
no intra-workspace dependencies of its own.

Schema is managed with Alembic (`alembic.ini` + `migrations/`). The history
starts from a single squashed baseline, `migrations/versions/0001_initial_schema.py`,
which applies a verified schema-only dump; `migrations/versions/*` is excluded
from Ruff. Apply migrations with `make migrate`, create a new revision with
`make migrate-new msg="…"`, and roll back one with `make migrate-down`. Heed the
Database Safety Rules above — never run migrations against a production database
without explicit permission.

## Service tier & gateway

All client traffic enters through the **gateway** (`packages/gateway`, `:8000`),
which handles auth, rate limiting, and routing to the domain microservices.
The eight services each own one domain and run on fixed ports: `auth` (`:8001`),
`dataset` (`:8002`), `tool` (`:8003`), `pipeline` (`:8004`), `agent` (`:8005`),
`notification` (`:8006`), `app` (`:8007`), `task` (`:8008`). In dev they run on
the host via `make dev-<name>`; each imports `core` and talks to the others
through the gateway or the service URLs in `.env`.

The **Platform Assistant** (`packages/platform-assistant`) is the built-in agent
that the agent-service depends on. External packages can contribute extra
assistant tools by declaring a `techneos.platform_assistant_tools` entry point;
non-platform agents register through the `techneos.agents` group. The
agent-service pip-installs those packages from the configured package index
(DevPI locally) at startup, then discovers their entry points — so `core` carries
no hard dependency on optional tool/agent content.

## Client packages (CLI & management)

Two client packages talk to the platform **only through the gateway REST API**,
never the database directly:

- `packages/cli` — the `techneos` end-user command (Typer/Rich). Run it with
  `make dev-cli cmd="…"` or `uv run techneos …`.
- `packages/management` — the admin/registration toolkit, published as the
  `techneos-management` wheel. It holds the resource-removal scripts and the
  `management.registration` helpers (auth, environment/URL resolution, build +
  register orchestration) that every package's `build_and_register.py` imports.
  It's a **published dependency**: the platform's own publish scripts and
  externally-authored catalog packages both import `management.registration`, so
  its distribution name and import path are a stable contract — don't rename them
  casually.

## Keycloak DB auto-creation

The compose file has a `keycloak-init` service (a plain `postgres:16-alpine`
container running `psql`/`pg_isready`) that creates the `keycloak` Postgres
database before the `keycloak` service starts — Keycloak creates its own schema
on boot but not the database itself. Local dev's Keycloak uses Postgres
(`KC_DB=postgres`) rather than an embedded dev database, so it shares the same
storage backend as the rest of the stack.

## Documentation Maintenance

**Every PR must include documentation updates when the change affects documented behavior.**

Before finalizing a PR, review and update the following files as needed:

| File | Update when... |
|------|---------------|
| `README.md` | Project structure, setup steps, features, config, or deployment changes |
| `AGENTS.md` | Build commands, conventions, architecture/testing patterns, or subsystem notes change |
| `docs/architecture.md` | New services, tables, infrastructure, protocols, or architectural decisions |

Specifically, update docs when you:
- Add, remove, or rename a service, package, or CLI command
- Add or modify database tables or migrations
- Change environment variables or configuration
- Modify build, test, or deployment commands
- Introduce new architectural patterns or dependencies
- Change ports, URLs, or infrastructure requirements

If none of the above apply, no doc changes are needed.
