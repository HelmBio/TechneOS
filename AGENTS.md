# AGENTS.md

Single source of truth for all coding agents (Claude Code, opencode, Codex,
Cursor, …) working on this codebase. **Part 1 — Working Agreement** covers
safety rules, build/test/deploy, layout, and conventions. **Part 2 — Subsystem
Notes & Gotchas** captures per-feature implementation details.

> **This is a living document — keep it current.** It describes the repository
> as it stands *today*, not the final design. When a commit adds a package,
> command, convention, or subsystem, update the relevant section in the same
> commit. Today the repo contains the architecture design, a local Docker
> development stack with **Keycloak SSO** (Google + GitHub), the foundation
> Python layer (shared **core** library, **tool-runtime**, Alembic
> **migrations**), the **service tier** (API gateway, eight domain
> microservices, Platform Assistant), the **client tier**: the `techneos` CLI
> and the `management` toolkit, and the **web portal** (Next.js). There is no
> execution layer or test suite yet — those land in subsequent commits, and
> the rules below that reference them take effect as they arrive.

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
make up             # start the local Docker infra (Postgres, MinIO, Valkey, DevPI, Keycloak)
make install        # install the uv workspace (core, tool-runtime, services, ...)
make install-portal # install the web portal's npm dependencies
make migrate        # apply Alembic migrations (make migrate-new / migrate-down also available)
make seed           # create default roles, org, team, and an admin user (run after migrate)
make lint           # ruff check
make format         # ruff format + autofix
make typecheck      # mypy packages/
make test-portal    # run the web portal's vitest suite
make ps             # show running services
make logs           # tail service logs
make down           # stop services (down-v also removes volumes)
make clean          # remove build artifacts and caches
```

Run a backend in dev mode with `make dev-gateway` (the API gateway on `:8000`) or
`make dev-auth` / `dev-dataset` / `dev-tool` / `dev-pipeline` / `dev-agent` /
`dev-notification` / `dev-app` / `dev-task` for the individual services. `make
dev-all` starts every backend service at once via [`bin/dev.sh`](bin/dev.sh)
(`make dev-stop` stops them); `make dev-all-portal` also starts the web portal.
`make dev-portal` runs just the portal (`:3000`) against whichever gateway is
already running, and `make build-portal` produces its production build. A
Python test suite is added in a later commit.

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

Schema is managed with Alembic (`alembic.ini` + `migrations/`). The full schema
is defined in a single baseline migration, `migrations/versions/0001_initial_schema.py`;
`migrations/versions/*` is excluded from Ruff. Apply migrations with `make migrate`, create a new revision with
`make migrate-new msg="…"`, and roll back one with `make migrate-down`. Heed the
Database Safety Rules above — never run migrations against a production database
without explicit permission.

After migrating, `make seed` runs `core/database/seed.py` to create default
roles, a default org/team, and an admin user (`admin@example.com` /
`changeme123`, from `.techneos.<environment>.json` — falls back to the
committed `.techneos.example.json` if no environment-specific file exists).
Idempotent: re-running it upserts roles and only fills in missing fields on
existing rows, so it's safe to run again after a `make down-v && make up`
against a fresh volume.

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

## Web portal

`packages/portal` (Next.js 16 / React 19 / TypeScript / Tailwind CSS v4) is a
separate npm package, **not** part of the root `pyproject.toml` uv workspace —
install it with `npm install` (or `make install-portal`), not `uv sync`.

- Talks to the platform **only through the gateway REST API** (`@/lib/api`),
  same as the CLI — never the database, never a backend service directly.
  `next.config.ts` rewrites `/api/v1/*` to the gateway URL so the browser sees
  everything same-origin (required for cookie-based sessions and iframe-embedded
  Apps).
- `bin/generate-portal-env.sh` derives the portal's `NEXT_PUBLIC_*` build-time
  vars from the repo-root `.env`'s `PLATFORM_*` vars into `packages/portal/.env.local`
  (gitignored, regenerated on every `dev-portal` / `dev-all-portal` /
  `install-portal` / `build-portal` run) — never hand-edit `.env.local`.
- Branding (site name, tagline, icon) is centralized in `src/lib/site-config.ts`,
  overridable via `NEXT_PUBLIC_SITE_NAME` / `NEXT_PUBLIC_SITE_TAGLINE`.
- Tests use Vitest + Testing Library (`src/__tests__/`); run with `make test-portal`.

## Authentication (Keycloak SSO)

The compose file has a `keycloak-init` service (a plain `postgres:16-alpine`
container running `psql`/`pg_isready`) that creates the `keycloak` Postgres
database before the `keycloak` service starts — Keycloak creates its own schema
on boot but not the database itself. Local dev's Keycloak uses Postgres
(`KC_DB=postgres`) rather than an embedded dev database, so it shares the same
storage backend as the rest of the stack.

`keycloak/techneos-realm.dev.json` is volume-mounted into the
`keycloak` service's import directory and auto-imported on startup
(`kc.sh start-dev --import-realm`) — it defines the `techneos` realm, the
`techneos-api` / `techneos-web` clients, and Google + GitHub identity
providers. Local email/password login works out of the box with no further
setup. To enable the Google/GitHub buttons on the portal's login page:

1. Uncomment the `KEYCLOAK_*` vars in `.env` (see `.env.example`) so
   `keycloak_configured` is true — this is what makes the frontend's
   `/api/v1/auth/oidc/config` response include Keycloak, and the login page's
   `showGoogle`/`showGitHub` flags render the buttons.
2. Register your own OAuth apps (Google Cloud Console, GitHub OAuth Apps) and
   set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`/`GITHUB_CLIENT_ID`/`GITHUB_CLIENT_SECRET`
   in `.env` — the realm file wires these in via env var substitution, so
   nothing else needs editing.
3. `make down-v && make up` for a fresh Postgres volume (Keycloak only
   imports a realm the first time its DB is created).

Redirect URIs in the realm file assume `localhost:3000` (portal) and
`localhost:8080` (Keycloak) — update both the realm file and your OAuth app's
authorized redirect URIs together if you change ports/hosts.

**Rotating OAuth credentials later:** the `${GOOGLE_CLIENT_ID}`-style env var
substitution in `keycloak/techneos-realm.dev.json` only happens once, at
first import. If you change `GOOGLE_CLIENT_ID`/`GITHUB_CLIENT_ID`/etc. in
`.env` afterward, the running realm keeps the stale values — recreating the
`keycloak` container updates its own environment but not the identity
provider config already stored in Keycloak's database. Run
`make sync-idp-secrets` ([`bin/sync-keycloak-idp-secrets.sh`](bin/sync-keycloak-idp-secrets.sh))
to push the current `.env` values into the running realm via the Keycloak
admin CLI, without a full `make down-v` reset (which would also wipe seeded
roles/org/users and anything else in Postgres).

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
