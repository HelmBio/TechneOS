# ADR-001: Gateway as Package Index Proxy

**Status:** Accepted

**Date:** 2026-07-22

## Context

Catalog clients (scripts, tools, agents) currently publish wheels directly to the underlying package index (CodeArtifact in production, devpi in development) and resolve packages from it. This creates several problems:

1. **Credential exposure:** Clients need direct access to index credentials (CodeArtifact tokens, devpi passwords)
2. **Inconsistent access:** Different environments (local vs. prod) require different client configurations
3. **No centralized control:** The platform cannot enforce policies on package operations
4. **Tight coupling:** Clients are coupled to specific index implementations

## Decision

The gateway becomes the sole proxy for all package operations. Clients never connect directly to the underlying index or docker registry.

### Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│   Catalog   │────▶│   Gateway   │────▶│  Index (CA/devpi)│
│   Client    │     │             │     │                 │
│             │◀────│  /simple/*  │◀────│                 │
└─────────────┘     └─────────────┘     └─────────────────┘
      │                    │
      │ POST /artifacts/*  │ uv publish / docker push
      └───────────────────▶│─────────────────────────▶ Registry (ECR)
```

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/v1/artifacts/wheel` | admin | Upload .whl, gateway publishes to index |
| POST | `/api/v1/artifacts/image` | admin | Upload .tar, gateway pushes to registry |
| GET | `/simple/` | public | List all packages (proxy to index) |
| GET | `/simple/{pkg}/` | public | List versions (proxy to index) |
| GET | `/simple/{pkg}/{filename}` | public | Download wheel (proxy to index) |

### Environment Variables

Standardized naming across local and production:

| Variable | Local Dev | Prod/EC2 |
|----------|-----------|----------|
| `PYTHON_PACKAGE_PUBLISH_URL` | `http://localhost:3141/` | CodeArtifact endpoint |
| `PYTHON_PACKAGE_INDEX_URL` | `http://localhost:3141/simple/` | CodeArtifact `/simple/` |
| `PYTHON_PACKAGE_USERNAME` | `devpi` | `aws` |
| `PYTHON_PACKAGE_PASSWORD` | `devpi` | (empty - uses token) |
| `DOCKER_IMAGE_REGISTRY` | (empty) | ECR URL (IAM auth) |
| `CODEARTIFACT_DOMAIN` | (empty) | `techneos` |
| `CODEARTIFACT_DOMAIN_OWNER` | (empty) | AWS account ID |
| `CODEARTIFACT_REPOSITORY` | (empty) | `techneos-packages` |

## Consequences

### Positive

- **Centralized credential management:** Gateway owns all index/registry credentials
- **Simplified client config:** Clients only need gateway URL and auth token
- **Consistent behavior:** Same flow across local dev and production
- **Security:** Credentials never leave the gateway; upload endpoints require admin auth
- **Flexibility:** Gateway can add caching, rate limiting, or logging without client changes

### Negative

- **Single point of failure:** Gateway outage blocks all package operations
- **Performance overhead:** Extra hop for package resolution
- **Gateway complexity:** Gateway now handles package publishing in addition to API routing

### Mitigations

- Gateway is already a required component (all API calls go through it)
- Package resolution is cached by pip/uv locally
- Gateway publishing logic is isolated in `publish.py` module

## Implementation

See commit `693c97f` for the full implementation:

- `packages/gateway/src/gateway/publish.py` - Publishing utilities
- `packages/gateway/src/gateway/routes/artifacts.py` - Upload and proxy routes
- `packages/management/src/management/registration.py` - Client upload functions
- `packages/management/src/management/catalog.py` - Uses gateway variants by default
