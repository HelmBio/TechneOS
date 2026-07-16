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
> and the `management` toolkit, the **web portal** (Next.js), the
> **execution layer** (Apache Airflow DAGs + compute backends), and a
> **test suite** (`tests/unit` + `tests/integration`). The production
> deployment assets land in a subsequent commit.

---

# Part 1 — Working Agreement

## CRITICAL: Database Safety Rules

**NEVER perform Create, Update, or Delete operations against the production database without explicit user permission.** This includes:

- Running tests that connect to the production database (`techneos`)
- Running seed scripts or migrations against production
- Writing integration tests that use the production database
- Any code that could modify, truncate, or drop production tables

All tests MUST use the `techneos_test` database (never the primary `techneos` database) — the test conftest force-sets `POSTGRES_DB=techneos_test`. Integration tests must be marked `@pytest.mark.integration` and are excluded from the default test run (`make test`); run them explicitly with `make test-integration`.

If you need to run anything against production data, **ask the user first**.

**NEVER reset a user's password by directly updating `hashed_password` in the database.** Use the `PUT /admin/users/{user_id}/reset-password` API endpoint instead (requires `platform_admin` role). Direct DB password mutations bypass audit logging and password policy validation.

## CRITICAL: Git Commit Policy

**NEVER automatically commit changes to `main`.** Work on a feature branch and
commit there as you go — that is what branches are for, and a reviewable series of
commits beats a pile of unstaged edits.

What needs the user's word is **landing**: `git merge` onto `main` and `git push`.
Wait for an explicit instruction each time; approval for one merge is not approval
for the next. Branches stay local — only `main` is ever pushed, via
`git merge --ff-only <branch>` then a single push.

## Build & Run

The Makefile targets available today (run `make help` for the list):

```bash
make up             # start the local Docker infra (Postgres, MinIO, Valkey, DevPI, Keycloak, Airflow)
make install        # install the uv workspace (core, tool-runtime, services, ...)
make install-portal # install the web portal's npm dependencies
make migrate        # apply Alembic migrations (make migrate-new / migrate-down also available)
make seed           # create default roles, org, team, and an admin user (run after migrate)
make lint           # ruff check
make format         # ruff format + autofix
make typecheck      # mypy packages/
make test           # Python tests, excluding integration (make test-unit / test-cov also available)
make test-integration  # integration tests (requires the stack up)
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
already running, and `make build-portal` produces its production build. See
the Testing section for `make test` / `test-integration` and the per-package
test targets.

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

`make backup` ([`bin/backup.sh`](bin/backup.sh)) captures everything the platform
keeps state in — the `techneos` and `airflow` databases, the object store bucket,
and the Valkey RDB — into `./backups/<timestamp>/`, alongside a generated
`RESTORE.md` carrying the exact restore commands for that backup. It resolves
containers by Compose service label rather than by name, so it works whatever the
project is called. It exits non-zero and names what it missed if any component
could not be captured; a backup tool reporting success it didn't earn is worse
than one that fails. `backups/` is gitignored: those dumps are real user data.

After migrating, `make seed` runs `setup/database/seed.py` to create default
roles, a default org/team, and an admin user (`admin@example.com` /
`changeme123`, from `setup/database/.techneos.<environment>.json` — falls back to the
committed `setup/database/.techneos.example.json` if no environment-specific file exists).
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

- `packages/cli` — the `techneos` end-user command (Typer/Rich), published as the
  `techneos-cli` wheel. Run it with `make dev-cli cmd="…"` or `uv run techneos …`.
  It's the one package customers install on their own machines, which constrains
  it: it depends only on typer/httpx/rich — **never on `core`** or anything else
  in this workspace — and reaches the platform solely over the gateway's REST
  API. Its import package is `techneos_cli`, not `cli`: the wheel lands in a
  customer's site-packages, where a generic top-level name would collide with
  their own modules. The gateway serves the wheel (see "CLI distribution").
- `packages/management` — the admin/registration toolkit, published as the
  `techneos-management` wheel. It holds the resource-removal scripts and the
  `management.registration` helpers (auth, environment/URL resolution, build +
  register orchestration) that the setup scripts and catalog
  `build_and_register.py` scripts import.
  It's a **published dependency**: the platform's own setup scripts and
  externally-authored catalog packages both import `management.registration`, so
  its distribution name and import path are a stable contract — don't rename them
  casually.

### CLI distribution

Each deployment serves its own client wheel; nothing is published to PyPI. The
gateway image builds `packages/cli` into `/app/cli-dist` and exposes it at
`/cli/simple/` ([`gateway/routes/cli.py`](packages/gateway/src/gateway/routes/cli.py)),
so the CLI a customer installs is the one built from the image they install it
from. Locally, `make build-cli-wheel` fills the same directory (`cli_wheel_dir`,
relative to the process CWD). The index re-reads that directory per request, so
a rebuilt wheel needs no gateway restart.

[`bin/build-cli-wheel.sh`](bin/build-cli-wheel.sh) stamps local builds with the
commit they came from — `0.1.0+g1a2b3c4`, plus `.d<digest>` of the package's
sources when it has uncommitted changes. That isn't cosmetic: **pip and uv key
their caches on name + version**, so a rebuild carrying a version already
installed is invisible to them. They report success and leave the copy they had,
which reads as "my change did nothing". `pipx` compounds it — its `--force` is
broken with the uv backend (it calls `uv venv` without `--clear`), and `uv cache
clean` can block on the cache lock while the dev stack holds it. A distinct
version per build sidesteps all of that.

The digest is why it's a digest and not a `.dirty` flag: a flag is the same
string on every rebuild, so it fails for exactly the loop the stamp exists for —
editing without committing. Keying on content means the version changes when, and
only when, the code does, so an unchanged rebuild is still a legitimate cache hit.

The gateway image builds from `pyproject.toml` directly, so release wheels carry
the plain version; each release is a version customers haven't installed before,
which is why their caches were never the problem.

Two constraints are easy to break:

- **It is a PEP 503 index, not a download URL.** pip takes a wheel's filename
  from the URL it is handed — it ignores `Content-Disposition` and won't re-read
  the name after a redirect — so a `/cli/download` endpoint cannot yield a
  version-free install command. An index can.
- **Unknown projects redirect to PyPI**, which is what lets the index be a
  client's only `--index-url`. Don't "simplify" that away and tell users to add
  PyPI as an `--extra-index-url`: pip merges indexes and takes the highest
  version across all of them, so anyone registering the unclaimed `techneos-cli`
  name on PyPI could outrank the wheel we serve.

`/cli/` is unauthenticated (`PUBLIC_PREFIXES`) — a customer installs the client
before they have any credentials. Downloads are restricted to the wheels the
index itself enumerates, so a crafted filename can't reach other files. The
schema's security is cleared for those prefixes too, so the lock icons in
`/docs` keep matching what the middleware actually enforces.

Only `GET /cli/version` is in the OpenAPI schema. The index pages and the wheel
are `include_in_schema=False`: they serve HTML and binaries to a package
installer, so a "Try it out" button on them is noise.

Skew is advisory: the CLI sends `X-Client-Version` on every request and the
gateway answers with `X-Client-Version-Warning` when the versions are
incompatible ([`gateway/client_version.py`](packages/gateway/src/gateway/client_version.py)).
The rule is semver-aware — before 1.0 a minor bump breaks, after it only a major
one does. `PLATFORM_VERSION` there is what clients are compared against; keep it
in step with the gateway package version.

## Platform setup (`setup/`) & the catalog contract

`setup/` holds the platform-admin operations run once on a fresh deployment,
after infra + schema are up (`make up`, `make migrate`) and **before** any
catalog items are registered. These scripts are **not** part of any shipped
wheel and are **not** imported by the services at runtime — they write to the
DB or drive the gateway API directly:

- `setup/database/seed.py` (`make seed`) — default roles, org/team, admin user. Reads
  `setup/database/.techneos.<env>.json`.
- `setup/wheels/{tool_runtime,management}.py` (`make publish-wheels`, via
  `bin/build-register-platform-wheels.sh`) — build + publish the two wheels a
  catalog repo depends on (`techneos-tool-runtime`, `techneos-management`) to
  the package index, and record them in the `compute_artifacts` inventory.
- `setup/register_platform_assistant.py` (`make register-platform-assistant`) —
  create the default LLM provider + the built-in Platform Assistant agent via
  the gateway API. (Needs the stack up + an admin token.)
- `setup/register_compute_artifacts.py` — ingest a build-artifacts manifest
  into the `compute_artifacts` inventory.

**Zero runtime coupling:** services never import these. The one read helper
they *do* share — `core.database.compute_artifacts.find_artifact` — stays in
`core` (it's a pure inventory lookup, not seeding). Ruff lints `setup/`; mypy
does not (operational scripts, like `packages/execution`).

**The catalog repo contract.** The separate `techneos-catalog` repo holds the
tools/agents/datasets/pipelines/apps. Each catalog package:
- depends on **`techneos-management`** (in its `publish`/`tooling` dep group) —
  its `build_and_register.py` imports `management.registration` /
  `management.catalog`;
- pypi tools are built for and dispatched into the **`techneos/tool-runtime`**
  worker image;
- contributes assistant tools via the `techneos.platform_assistant_tools`
  entry-point group, and non-platform agents via `techneos.agents` (both
  discovered lazily by the agent-service — `core` has no hard dependency on
  catalog content).

So `make publish-wheels` is what makes a catalog checkout resolvable: without
those two wheels on the index, catalog `build_and_register.py` scripts can't
install their build dependency.

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

## Execution layer (Airflow)

`packages/execution` holds the pipeline orchestration layer: Airflow DAGs
(`dags/dag_factory.py` builds a DAG per pipeline run), the `ToolOperator`
(`operators/`) that dispatches each step, status callbacks to the platform
(`callbacks/`), MinIO artifact I/O (`storage/`), and pluggable compute
backends (`backends/`: Docker, AWS Batch, Slurm, and a human-task backend).

Key facts for anyone working here:

- **Not a uv workspace member** (excluded in `pyproject.toml`). It runs inside
  the Airflow containers, which install `apache-airflow` themselves and mount
  `dags/`, `operators/`, `callbacks/`, `backends/`, `storage/` **flat** under
  `/opt/airflow/` — which is why its modules import each other by bare name
  (`from backends.base import ...`), not as `packages.execution.*`.
- Because `airflow` isn't installed in the typed platform environment, the
  package is **excluded from mypy**; ruff still lints it, and it must stay
  ruff-clean. Its unit tests live in `packages/execution/tests/` and run with
  `PYTHONPATH=packages/execution` (they don't need Airflow).
- The DAG reports step status back to the gateway using the shared
  `INTERNAL_SERVICE_TOKEN` (the gateway's `X-Internal-Token` path). Set a real
  value in `.env` — a blank token disables those callbacks.
- Which backend runs a step is chosen by the step's `resource_requirements`
  and the `COMPUTE_BACKEND` env var (`docker` locally, `aws_batch` in cloud).
- `airflow-init` creates the `airflow` Postgres database and an admin user on
  first `make up`; the webserver is on `:8082` (admin/admin by default). The
  DAG id is `techneos_airflow_pipeline`.

## Testing

### Where tests live (the principle)

**A package is tested at exactly one level — never both.** The dividing line
is *where the package runs*: the server-side platform is tested top-level;
anything shipped or executed **outside** the platform deployment owns its
tests in-package.

- **Server-side platform** — `core`, `gateway`, and the eight `services/*` —
  is tested in the **top-level `tests/`** suite. Its tests routinely cut across
  packages (a route test touches `core` models, service CRUD, and gateway auth
  at once) and rely on the assembled uv workspace. These packages carry **no
  `tests/` directory of their own**.
- **Packages shipped/run outside the platform** own their tests **in-package**,
  because they're consumed by customers or run in a separate runtime, have no
  intra-workspace (`core`) dependency, and are exercised in isolation:
  - `cli` → `packages/cli/tests/` — the `techneos-cli` client wheel customers
    install; talks to the platform only over the gateway REST API, which the
    tests mock (`make test-cli`).
  - `management` → `packages/management/tests/` — the `techneos-management`
    client wheel (also imported by the external catalog repo); talks to the
    gateway REST API + AWS, both mocked in tests (`make test-management`).
  - `tool-runtime` → `packages/tool-runtime/tests/` — the published foundation
    wheel tool authors build against (`make test-tool-runtime`).
  - `execution` → `packages/execution/tests/` — excluded from the uv workspace
    (runs inside the Airflow containers), so it can't be collected by the
    workspace suite; run via `PYTHONPATH=packages/execution`
    (`make test-execution`).
  - `portal` → `packages/portal/src/__tests__/` — a different language and
    runner (Vitest), per Next.js convention (`make test-portal`).

  A package in this second group must **not** also be tested from the
  top-level suite. `make test-all` runs every level together.

  Rule of thumb: if a package has no `core` dependency and its tests need
  nothing from the shared `tests/conftest.py`, it belongs in-package.

### Conventions (enforced by config)

- **`tests/conftest.py` sets the test environment** before any import:
  `POSTGRES_DB` is *force-set* to `techneos_test` (so a stray run can never
  touch the primary DB), and dev values for `JWT_SECRET_KEY` /
  `SECRETS_ENCRYPTION_KEY` / etc. are `setdefault`-ed (honoring anything CI
  already exported). Mirror this pattern when a new test needs a secret.
- **Integration tests are marked `@pytest.mark.integration`** and excluded
  from the default run via `addopts = -m 'not integration'`. `make test`
  runs everything except integration; `make test-integration` runs only
  them and needs `make up` first. `pytest-asyncio` is in `auto` mode, so
  `async def test_*` needs no decorator.
- **Tests are excluded from mypy** (`/tests/` in the exclude list) but **are
  linted by ruff**. Two pep8-naming rules (`N806`, `N803`) are ignored under
  `tests/**` because mocked classes idiomatically keep PascalCase names
  (e.g. `patch(...) as MockClient`).

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
