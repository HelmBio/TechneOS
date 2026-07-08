# TechneOS — Architecture Design Document

## Overview

An AI-powered data and computing platform for drug discovery. The platform hosts
datasets, computing pipelines, AI agents, tools, and apps for organizations, teams,
and users. Authorized users access the platform via a web portal, RESTful API, or
CLI to register catalog items, execute pipelines/tools, and view results. The
platform runs today as a single-host deployment; its services are decomposed
so that a future multi-host rollout does not require rewriting them.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     CLIENT LAYER                             │
│  ┌──────────┐   ┌──────────────┐   ┌─────────────────┐      │
│  │ Web Portal│   │ RESTful API  │   │   CLI Client    │      │
│  │ (Next.js)│   │ (OpenAPI)    │   │ (Python/Typer)   │      │
│  └────┬─────┘   └──────┬───────┘   └───────┬─────────┘      │
└───────┼────────────────┼───────────────────┼─────────────────┘
        │                │                   │
┌───────▼────────────────▼───────────────────▼─────────────────┐
│                    API GATEWAY                                │
│         JWT/API-key auth · SSE-aware reverse proxy            │
└───────────────────────┬───────────────────────────────────────┘
                        │
┌───────────────────────▼───────────────────────────────────────┐
│                  SERVICE LAYER (8 FastAPI microservices)       │
│                                                                 │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │ Auth       │ │ Dataset    │ │ Tool       │ │ Task       │  │
│  │ (users,    │ │ Service    │ │ Service    │ │ Service    │  │
│  │  RBAC,     │ │            │ │ (registry +│ │ (human-in- │  │
│  │  audit log)│ │            │ │  tool runs)│ │  the-loop) │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐  │
│  │ Pipeline   │ │ Agent      │ │ App        │ │Notification│  │
│  │ Service    │ │ Service    │ │ Service    │ │ Service    │  │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                  COMPUTE LAYER                                │
│  ┌─────────────────┐  ┌────────────────────────────────────┐ │
│  │ Workflow Engine  │  │ Compute Backends (pluggable)       │ │
│  │ (dynamic DAG,    │  │ Docker · AWS Batch · Slurm · Human │ │
│  │  REST API only)  │  │                                    │ │
│  └─────────────────┘  └────────────────────────────────────┘ │
└──────────────────────┬────────────────────────────────────────┘
                       │
┌──────────────────────▼────────────────────────────────────────┐
│                  DATA LAYER                                     │
│  ┌──────────┐ ┌───────────┐ ┌──────────┐                      │
│  │ Postgres │ │ Object    │ │ Valkey   │                      │
│  │ (metadata│ │ Store     │ │ (cache + │                      │
│  │  + JSONB)│ │ (MinIO)   │ │  pub/sub)│                      │
│  └──────────┘ └───────────┘ └──────────┘                      │
└─────────────────────────────────────────────────────────────────┘
```

Every service is a standalone application sharing a common core library
(config, DB session, models, auth, object store, cache, agent bridge). Audit
logging is a capability of the auth service, not a separate service. The
gateway is the only component clients talk to; it authenticates each request
and reverse-proxies it to the owning service over plain HTTP, with a
streaming (non-buffered) path for Server-Sent Events endpoints (agent chat,
assistant chat, run monitoring).

| Service | Responsibility |
|---|---|
| Auth | Users/orgs/teams, RBAC roles & permissions, API keys, JWT issuance, LLM provider CRUD, audit log |
| Dataset | Dataset + dataset-version metadata, object-store refs |
| Tool | Tool registry, tool versions, compute-backend registry, compute-artifacts inventory, standalone tool runs |
| Task | Human-in-the-loop task runs (assignment, events, artifacts) — the runtime side of the `human` tool type |
| Pipeline | Pipeline (shape) + pipeline-version (binding) metadata, pipeline runs, workflow-engine dispatch |
| Agent | Agent definitions, agentic runs/tasks, LLM-backed execution, SSE streaming, Platform Assistant + delegation |
| App | Registered interactive web apps, embedded-app container deploy + iframe runtime proxy |
| Notification | Subscriptions and in-app notifications |

---

## Technology Decisions

| Concern              | Choice                        | License          | Rationale                                                         |
|----------------------|-------------------------------|------------------|-------------------------------------------------------------------|
| Backend framework    | Python 3.12 / FastAPI         | MIT              | Async, auto OpenAPI, native ML ecosystem                          |
| Primary database     | PostgreSQL 16                 | PostgreSQL Lic.  | ACID, JSONB for semi-structured data                              |
| Object storage       | MinIO                         | AGPL-3.0         | S3-compatible, self-hostable                                      |
| Cache / pub-sub      | Valkey                        | BSD-3            | Redis-compatible, fully open source fork; also backs the notification event bus |
| Workflow engine      | Apache Airflow                | Apache 2.0       | Mature DAG orchestration; integrated purely through its REST API  |
| Auth                 | Built-in JWT + Keycloak + OAuth2 | MIT / Apache 2.0 | Multi-provider: local JWT, Keycloak (social login), generic OAuth2 (enterprise SSO) |
| Frontend             | Next.js                       | MIT              | SSR + SPA, file-based routing                                     |
| CLI                  | Python / Typer                | MIT              | Developer/scientist workflow                                      |
| ORM                  | SQLAlchemy 2.0 (async)        | MIT              | Mature, async support, Alembic migrations                         |
| Package manager      | uv                            | MIT/Apache 2.0   | Fast Python package management                                    |
| Container runtime    | Docker / Docker Compose       | Apache 2.0       | Single-host dev and prod deployment                                |
| Observability        | Structured request logging + per-service health checks | — | No metrics/dashboarding backend wired up yet          |
| All dependencies     | Open source only              | —                | No proprietary vendor lock-in                                     |

---

## Deployment

The platform runs as one Docker Compose stack per environment — there is no
Kubernetes deployment today.

- **Local dev**: a Compose stack brings up Postgres, MinIO, Valkey, a local
  Python package index, Keycloak, and the workflow engine (webserver +
  scheduler). The application services and the portal run directly on the
  host, talking to the containerized dependencies.
- **Production**: a single host runs every service behind a reverse proxy.
  Deploys go through a CI/CD pipeline: a build stage builds and pushes every
  image to a container registry, a manual approval gate, then a deploy stage
  ships the compose bundle to the host and applies it via remote command
  execution — no SSH keys, no hardcoded instance address. The same deploy
  step runs database migrations, seeds default data, and ensures baseline
  admin credentials, on every deploy.
- **Secrets**: the full production environment is rendered at deploy time
  from a secrets manager; nothing is shipped from a developer machine.
- **Infra as code**: the batch compute queue, the HPC cluster config, and the
  CI/CD pipeline itself are all defined as infrastructure-as-code, not
  clicked together by hand.

---

## Embedded Apps

Apps in the **Apps** category are interactive web tools (viewers, editors,
notebooks, ML playgrounds) that users launch from the platform UI. Each App
is registered with a launch mode:

| Mode      | Where it runs                          | Auth path                                | When to use                              |
|-----------|-----------------------------------------|-------------------------------------------|-------------------------------------------|
| `external`| Anywhere off-platform                  | App's own (or signed-JWT handoff)        | Existing third-party tools we link to    |
| `embedded`| Docker container on the platform host  | Platform session cookie via runtime proxy| Self-contained tools we ship             |

`embedded` Apps are deployed by the App service and reverse-proxied under a
per-app path prefix. The platform UI renders them inside an `<iframe>` —
**not** as an in-process React component.

### Why iframes, not React components?

The container + iframe model is deliberate. Each row below is a real driver,
not a hypothetical:

| Driver                  | Why iframe wins                                                                                                                                                                                       |
|-------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Polyglot apps           | An iframe doesn't care if the upstream is Next.js, Streamlit, Jupyter/Voila, Gradio, or a static HTML/WASM bundle. A React component would force every App to be a TS/React module.                    |
| Dependency isolation    | A given App may pin a different major version of a UI framework than the platform frontend uses. Containerizing keeps version conflicts inside the App image, not in the platform bundle.             |
| Independent versioning  | App images are tagged and redeployed without rebuilding/redeploying the platform frontend. The Apps registry stores the image reference.                                                                |
| Security sandboxing     | `<iframe sandbox=…>` plus the same-origin proxy give the platform a single auth + audit chokepoint per request, with browser-enforced isolation between the App and the platform DOM.                  |
| Lazy load               | The iframe only loads when the user opens the launch page. Platform bundle size stays flat regardless of how many Apps are registered.                                                                  |

A future `module` launch mode (Apps registered as a React/TS module loaded
via dynamic import or Module Federation) could be added if a use case
demands deep UI integration — but the current container/iframe model is
intentional, not a placeholder.

### Communication

The web frontend rewrites API requests to the gateway so the iframe `src`
stays same-origin. That lets the browser send the session's HTTP-only cookie
automatically — the gateway authenticates the request before forwarding it
to the App's runtime proxy. Because parent and frame share an origin, they
can also `postMessage` without cross-origin restrictions.

A deployment where the web frontend and the API live on different
subdomains (e.g. a `app.example.com` / `api.example.com` split) **must**
scope the session cookie to their shared parent domain. Otherwise the cookie
issued at login is scoped to the API subdomain only, the browser won't send
it on iframe loads against the web subdomain, and embedded Apps will
authenticate. Local dev doesn't need this — cookies on `localhost` ignore
the port and are shared between web and gateway anyway.

---

## Key Abstractions (Designed for Swappability)

### AuthProvider — per-request multi-provider model

```python
class AuthProvider(Protocol):
    async def validate_token(self, token: str) -> UserClaims: ...
    async def create_tokens(self, user_id: str, ...) -> TokenPair: ...
```

Three providers can run simultaneously (no global switch):

- `LocalAuthProvider` — self-signed HS256 JWTs, passwords in Postgres (always enabled)
- `KeycloakAuthProvider` — validates RS256 JWTs via JWKS, enables Google/GitHub social login (enabled when Keycloak connection settings are configured)
- `OAuth2AuthProvider` — exchanges authorization codes, introspects opaque tokens, issues local HS256 JWTs for enterprise SSO (enabled when a generic OAuth2 client is configured)

The sign-in method determines the provider: email/password uses local,
Google/GitHub use Keycloak, SSO uses OAuth2. All tokens issued to clients are
locally-signed HS256 JWTs.

### ObjectStore — swap between MinIO and cloud S3

```python
class ObjectStore(Protocol):
    async def put(self, bucket: str, key: str, data: BinaryIO, ...) -> str: ...
    async def get(self, bucket: str, key: str) -> BinaryIO: ...
    async def delete(self, bucket: str, key: str) -> None: ...
    async def presigned_url(self, bucket: str, key: str, ...) -> str: ...
```

### LLMProviderRegistry — bridge platform providers to agent frameworks

```python
# Loaded from LLMProvider DB rows at service startup
registry = get_registry()
provider = registry.get("some-provider-slug")  # → ProviderConfig
client = provider.build_client()                # → AsyncOpenAI(api_key=..., base_url=...)
model = OpenAIModel(name, provider=OpenAIProvider(openai_client=client))
agent = Agent(model=model, tools=[...], instructions="...")
```

The registry maps provider slugs to `ProviderConfig` instances. Each config
resolves its API key from an encrypted column (decrypted at runtime) and
builds an OpenAI-compatible client with the provider's base URL — supporting
any OpenAI-compatible API (OpenAI, Gemini via proxy, Azure, local models).
The crypto/DB-free registry core is kept separate from the DB-loading layer
that decrypts stored keys, so the registry itself has no encryption or
database dependency.

---

## RBAC Model

```
Roles (hierarchical):
  platform_admin > org_admin > project_lead > scientist > viewer

Permission format: resource:action:scope
  Resources: user, org, team, dataset, pipeline, pipeline-run, tool, tool-run,
             agent, agentic-run, agentic-task, app, result
  Actions:   create, read, update, delete, execute
  Scopes:    own, team, org, platform (or * to match any scope)

Endpoints use `require_permission(resource, action, scope)` where scope is the
minimum required scope. Using `"*"` delegates scope control entirely to the seed
data — add/remove permissions in the seed configuration to grant/revoke access
without code changes.

Examples:
  platform_admin  → *:*:platform
  org_admin       → *:*:org
  project_lead    → dataset:*:team, pipeline:*:team, tool-run:*:team, app:*:team, user:read:team, ...
  scientist       → dataset:create:own, dataset:read:team, pipeline:execute:own, tool-run:execute:own, ...
  viewer          → *:read:own
```

Resource scoping derives the caller's data-level access from the same
permission strings — one check gates a single resource instance, another
restricts list queries to what the user may see — so a role's scope is never
hard-coded per endpoint.

---

## Data Model (PostgreSQL)

The schema is managed as a single baseline migration; conceptually it groups
into the domains below.

### Identity & Access
- **orgs** — Organizations (tenants)
- **teams** — Teams within orgs
- **users** — User accounts (linked to org, team, role)
- **roles** — RBAC role definitions (name, permissions, description)
- **api_keys** — API key management (hashed, scoped)
- **audit_logs** — Auth events and admin actions
- **llm_providers** — LLM provider configurations (name, provider type, encrypted API key, model list, org scope, is_default flag)

### Catalog
- **datasets** / **dataset_versions** — Dataset metadata and immutable version snapshots (object-store refs, upload or bucket-transfer provenance)
- **tools** / **tool_versions** — Tool registry. The tool type is `container | pypi | human` in active use (a `module` type is legacy, superseded by `pypi`; an `api` type is defined but unused)
- **tool_docker_configs** / **tool_pypi_configs** / **tool_human_configs** — Per-tool-type execution config, one row per tool version
- **pipelines** — Pipeline metadata **+ the canonical DAG shape** (steps, edges, parameter schema, topology hash, forked-from ref). The shape is the pipeline's identity and is treated as immutable once created
- **pipeline_versions** — Per-version **binding** over the shape (step → {tool version, parameters}, status)
- **apps** / **app_launches** — Registered interactive apps and their launch history
- **agents** — AI agent configurations (type, framework, model settings, tools, a flag marking the built-in assistant)
- **compute_backends** — Enabled execution backends and their per-deployment config (job queue, submit host, etc.)
- **compute_artifacts** — Inventory of built & published wheels and docker images (origin: catalog or platform); tool-version creation is hard-validated against it

### Execution
- **pipeline_runs** / **pipeline_step_runs** / **pipeline_run_artifacts** — Pipeline execution records, per-step status, and run files (an io-type field distinguishes staged inputs from step outputs)
- **tool_runs** / **tool_run_artifacts** — Standalone (single-step) tool execution records and their files
- **task_runs** / **task_run_events** / **task_run_artifacts** — Human-in-the-loop task execution: current-holder state, an append-only action log (start/delegate/escalate/...), and every file tagged by the action that produced/consumed it
- **agent_runs** — A conversation/session grouping multiple agent tasks (title, summary, org/user ownership)
- **agent_task_runs** — A single agent invocation within a run (task, conversation history, tool calls, result), linked back to its run

### Notifications
- **subscriptions** — User subscriptions to resources (tools, datasets, agents, pipelines — including wildcard category subscriptions) for notification delivery
- **notifications** — Per-user notification records (type, title, message, read status, link)

### Platform
- **platform_settings** — Key/value platform-wide configuration

---

## Pipeline & Tool Execution Flow

```
User (Web/API/CLI)
  │
  ▼
API Gateway ──► Pipeline Service or Tool Service (Orchestrator)
                  │
                  ├── Validate definition, resolve tool versions
                  ├── Create run records (Postgres)
                  ├── Build step confs (image, params, resource_requirements)
                  │
                  ▼
              Workflow Engine REST API ──► Trigger the pipeline DAG
                  │
                  ▼
              ToolOperator per step:
                  │
                  ├── Select backend:
                  │     human tool_type  → HumanBackend (always)
                  │     otherwise        → resource_requirements.backend
                  │                        → COMPUTE_BACKEND env var
                  │                        → "docker" fallback
                  │
                  ├── backend.submit_job(spec)
                  │     Docker:    docker run + bind mount /work
                  │     AWS Batch: submit_job to queue
                  │     Slurm:     rsync inputs → SSH sbatch + Singularity
                  │     Human:     POST /api/v1/task-runs
                  │
                  ├── Poll backend.get_job_status() until terminal
                  ├── backend.collect_outputs()
                  ├── Upload artifacts → object store
                  ├── Register artifacts → Platform API
                  └── Report step status → Platform API (callback)
```

Both pipeline runs (multi-step) and standalone tool runs (single-step) use
the same DAG, operator, and backends — a standalone tool run just
synthesizes a one-element step list from the tool version's metadata. The
only difference is the callback path (pipeline runs vs. tool runs).

### Internal Service Token Authentication

Workflow-engine workers cannot use user JWTs. Instead, a shared secret is
sent as an internal-service-token header. Both the gateway and the owning
service's request-authentication layer recognize this header and treat the
caller as a synthetic platform-admin identity.

### Compute Backends

| Backend | Use Case | Notes |
|---------|----------|----------------|
| **Docker** | Local dev | `docker run` + reads step output from a host bind mount |
| **AWS Batch** | Cloud/prod | Submit to a Batch queue, poll job status, stage files via S3 |
| **Slurm** | On-premise HPC | SSH to a submit node, `sbatch` + Singularity/Apptainer, rsync in/out |
| **Human** | Human-in-the-loop | Creates task assignments in the task service, polls for completion (not a compute backend per se) |

Available backends are registered in a database table and exposed via a
read API. The tool version editor lets authors select a backend from a
dropdown; the API validates the choice against enabled backends.
Backend-specific config (job queue, submit host, etc.) is stored in the
table and injected into the workflow conf at dispatch time, so backends can
be configured per deployment without code changes.

### Human-in-the-Loop Tasks

A tool with a `human` tool type executes as a **task run** instead of a
compute job: the human backend posts a new task run to the task service,
which owns the full lifecycle — current holder, priority, due date,
assignment to a user or team — until someone submits or the run is
cancelled. The action log behind a task run is append-only and threaded, so
the current holder and full history are reconstructed from it rather than
kept in a separate assignment table.

---

## Agent System

Agent execution is built on an LLM-agent framework, bridged to the
platform's own provider/tool model:

- **The agent bridge** — the generic assembler. Resolves an agent
  definition's tools from a shared tool registry and its model from the LLM
  provider registry, wires them into a runnable agent. It has no
  assistant-specific knowledge; callers that need platform tools inject
  their own dependencies and default prompt.
- **The tool registry** — a flat, process-global map of tool function name →
  implementation. Agent packages self-register their tools on import (or at
  service startup); the agent service imports every known agent package so
  the bridge can resolve names at runtime.
- **The LLM provider layer** — a crypto/DB-free provider registry plus a
  thin DB-loading layer on top that decrypts each provider's stored API key
  only at that boundary.
- **Conversations**: a run groups multiple agent tasks together, replaying
  message history for multi-turn context.
- **Streaming**: both agent runs and assistant chat stream node-by-node
  execution — tool calls before execution, results after — over
  Server-Sent Events. The gateway detects SSE requests and proxies them
  without buffering.

### Platform Assistant

A built-in, always-on coordinator agent, marked with a platform flag and
auto-seeded on every service startup and deploy so it always exists. It
exposes built-in platform tools (list/get for datasets, tools, pipelines,
agents, apps, plus a platform-overview tool) and a delegation tool that lets
it invoke any other registered agent in-process and stream that delegation
as its own SSE events. All platform tools make authenticated calls back
through the gateway using the caller's own credentials.

### Catalog agents

Agents other than the Platform Assistant are authored and versioned outside
this codebase, as tool-only wheels — a pip-installable package exposing
entry-point tool functions, with no SDK dependency beyond the shared agent
bridge. The agent service installs a catalog agent's wheel at startup from
its registered package configuration and registers its tools by
introspecting the entry-point module.

---

## Notifications & Subscriptions

Users subscribe to individual resources (a dataset, tool, agent, pipeline)
or to an entire category via a wildcard subscription. Resource create/update
routes publish events (dataset created, dataset version uploaded, agent
created/updated, etc.) over a pub/sub event bus, with an HTTP fallback;
matching subscribers get a notification record and see it via the in-app
bell.

---

## Tool & Catalog Management

Catalog content (datasets, tools, pipelines, apps, non-platform agents) is
authored and registered from outside this codebase, all going through the
API gateway rather than direct database access. The client/registration
tooling for that — environment resolution, a login-token cache, and
register/build orchestration helpers — is kept as a separate package from
the shared core library, so the core library stays a pure runtime dependency
of the services rather than also being a client SDK. The same tooling
package ships the admin scripts used to unregister catalog content.

Every tool version's execution artifact (a pypi wheel or a docker image) is
hard-validated against a compute-artifact inventory at creation time,
populated by a push from the catalog build/registration step. All
compute/tool runtime images collapse to a single consolidated runtime image,
used both by the workflow engine's worker dispatch path and by container
tools themselves — one base image to build and patch, not several
near-duplicates.

---

## Compliance & Reproducibility

- **Compliance**: GxP-oriented audit trails (auth events + admin actions)
- **Reproducibility**: Every pipeline run is fully versioned (code, data,
  parameters, environment hash)
