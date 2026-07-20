# Platform setup

One-time (mostly) operations a **platform admin** runs on a fresh TechneOS
deployment — after the infrastructure and schema are up, and **before** any
catalog items can be registered. Everything here goes **through the gateway
API** (authenticating as the seeded admin); none of it touches the database
directly or ships in a wheel. The direct-DB bootstrap — `make seed` — lives
with the migrations it resembles (`migrations/seed/`), not here.

## Run order

```bash
# 0. Infra + schema (see the repo README)
make up
make migrate

# 1. Seed roles, org/team, admin user, and the default LLM provider (direct DB)
make seed                       # → migrations/seed/seed.py

# 2. Bring the services up
make dev-all                    # (or the production deploy)

# 3. Register the built-in Platform Assistant against the seeded provider
make register-platform-assistant   # → setup/register_platform_assistant.py

# 4. Build + publish the platform wheels the catalog imports, and record them
make publish-wheels             # → bin/build-register-platform-wheels.sh
```

## What each piece does

| Script | Make target | What it does | How it writes |
|--------|-------------|--------------|---------------|
| `register_platform_assistant.py` | `register-platform-assistant` | Register the built-in assistant agent against the seeded default provider | gateway API (needs admin token) |
| `wheels/publish_tool_runtime.py` | `publish-wheels` | Build/publish `techneos-tool-runtime`; build the runtime image | index + API |
| `wheels/publish_management.py` | `publish-wheels` | Build/publish `techneos-management` | index + API |

`register-platform-assistant` reads back the default LLM provider through the
API and points the assistant at it; if no provider exists it skips with a hint
to run `make seed` first. The provider itself — including its API key, taken
**only** from `DEFAULT_LLM_API_KEY` (never a committed file) — is created by
`make seed`; see `migrations/seed/` and `.env.example` for its config.

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
