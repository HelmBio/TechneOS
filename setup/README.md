# Platform setup

One-time (mostly) operations a **platform admin** runs on a fresh TechneOS
deployment — after the infrastructure and schema are up, and **before** any
catalog items can be registered. None of this ships in a wheel or runs inside
the services; it seeds the database and publishes the wheels a catalog repo
depends on.

## Run order

```bash
# 0. Infra + schema (see the repo README)
make up
make migrate

# 1. Seed roles, the default org/team, and the admin user
make seed                       # → setup/database/seed.py

# 2. Bring the services up
make dev-all                    # (or the production deploy)

# 3. Register the built-in Platform Assistant + its LLM provider (via the API)
make register-platform-assistant   # → setup/register_platform_assistant.py

# 4. Build + publish the platform wheels the catalog imports, and record them
make publish-wheels             # → bin/build-register-platform-wheels.sh
```

## What each piece does

| Script | Make target | What it does | How it writes |
|--------|-------------|--------------|---------------|
| `seed.py` | `seed` | Default roles, org, team, admin user | direct DB |
| `register_platform_assistant.py` | `register-platform-assistant` | Default LLM provider + built-in assistant agent | gateway API (needs admin token) |
| `wheels/publish_tool_runtime.py` | `publish-wheels` | Build/publish `techneos-tool-runtime`; build the runtime image | index + API |
| `wheels/publish_management.py` | `publish-wheels` | Build/publish `techneos-management` | index + API |
| `register_compute_artifacts.py` | — | Ingest a build-artifacts manifest into the inventory | direct DB |

Seed config lives in `setup/database/.techneos.<env>.json` (falls back to the committed
`.techneos.example.json`). The org, team, admin-user, and LLM-provider values can be
overridden per deployment with `DEFAULT_*` variables in `.env` (see `.env.example`);
role definitions stay in the JSON. The LLM provider's API key comes **only** from
`DEFAULT_LLM_API_KEY` — never a committed file — and `register-platform-assistant`
skips registration entirely if it (or any other required provider field) is missing.

## Enabling the catalog

The catalog (tools, agents, datasets, pipelines, apps) lives in a **separate
`techneos-catalog` repo**. Its packages depend on the two wheels published by
`make publish-wheels`:

- **`techneos-management`** — every catalog `build_and_register.py` imports
  `management.registration` / `management.catalog` to authenticate and register
  its resource through the gateway API.
- **`techneos-tool-runtime`** — pypi-type tools are dispatched into the
  `techneos/tool-runtime` worker image and build against it.

Until `make publish-wheels` has run against the target index (DevPI locally,
CodeArtifact in prod), a catalog checkout can't resolve its build dependency.
Catalog packages also contribute to the platform via entry-point groups
(`techneos.platform_assistant_tools`, `techneos.agents`), which the
agent-service discovers lazily — `core` has no hard dependency on catalog
content.
