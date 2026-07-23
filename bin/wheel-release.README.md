# wheel-release.sh

One tool to **release** Python package wheels (build → publish → register) in
either the local dev stack or the production EC2 deployment. It replaces the
old `bin/build-cli-wheel.sh` and `bin/build-register-platform-wheels.sh`.

```
bin/wheel-release.sh <package> [--env local|prod] [--skip-build] [--skip-register] [--force]
```

## What it releases

- **cli** — `techneos-cli` wheel (served by the gateway at `/cli/simple/`)
- **management** — `techneos-management` wheel (catalog registration scripts)
- **tool-runtime** — `techneos-tool-runtime` wheel (container tools base image)
- **platform** — all platform wheels (management + tool-runtime + cli)

## Flow

Default: **build → publish → register**

| Step | What happens |
|------|--------------|
| Build | `uv build` produces a `.whl` in the package's `dist/` directory |
| Publish | Wheel uploaded to the package index (DevPI locally, CodeArtifact in prod) |
| Register | Artifact recorded in the platform inventory (via gateway API) |

Use `--skip-build` to publish an existing wheel, or `--skip-register` to build
and publish without recording in inventory.

**Note:** The CLI wheel is served directly by the gateway from `cli-dist/`, not
published to the package index. Building CLI produces the wheel in `cli-dist/`.

## Version Handling

When a version already exists in the index:

- **Without `--force`** (default): Auto-bumps to `{version}-{git_sha}` with a
  warning to bump the version in `pyproject.toml` for the next release.
- **With `--force`**: Overwrites the existing version (for DevPI; CodeArtifact
  versions are immutable).

Example output when auto-bumping:
```
  Warning: Version 0.1.0 already exists in index.
  Auto-bumping to 0.1.0-a1b2c3d4e5f6 for this build.
  Bump the version in pyproject.toml for the next release.
```

## `--env local` vs `--env prod`

| | `--env local` (default) | `--env prod` |
|---|---|---|
| Publish target | DevPI at `localhost:3141` | CodeArtifact (from `.env.prod`) |
| Auth | `devpi` / `devpi` | AWS token (minted from IAM) |
| Register | Gateway at `localhost:8000` | Gateway from `.env.prod` |

## Examples

### 1. Release the CLI wheel

```bash
bin/wheel-release.sh cli
```

Builds and publishes the CLI wheel to the package index.

### 2. Release platform wheels to production

```bash
bin/wheel-release.sh platform --env=prod
```

Builds and publishes `techneos-management` and `techneos-tool-runtime` to
CodeArtifact, and builds the CLI wheel.

### 3. Republish an existing wheel (skip build)

```bash
bin/wheel-release.sh management --skip-build
```

Useful when the wheel is already built but you need to re-publish or re-register.

### 4. Build and publish without registering

```bash
bin/wheel-release.sh tool-runtime --skip-register
```

Builds and publishes to the index, but doesn't record in the platform inventory.

### 5. Release with custom auth

```bash
bin/wheel-release.sh management --env=prod --email user@example.com --password secret
```

### 6. Overwrite existing version

```bash
bin/wheel-release.sh management --force
```

Use when you need to overwrite an existing version in the index (e.g., after a
bugfix without bumping the version).

### 7. Reset index and inventory

```bash
bin/wheel-release.sh platform --reset
```

**Destructive operation.** Clears all techneos-* wheels from the package index
and marks all platform compute_artifacts as deleted. Requires confirmation.

## Options

| Flag | Description |
|------|-------------|
| `--env local\|prod` | Target environment (default: `local`) |
| `--skip-build` | Skip build step, publish existing wheel |
| `--skip-register` | Skip inventory registration |
| `--force` | Overwrite existing version in index (default: auto-bump) |
| `--reset` | Clear all wheels from index and platform records (destructive!) |
| `--email` | Auth email (for gateway login) |
| `--password` | Auth password (for gateway login) |
| `--upsert` | Upsert existing artifact instead of creating new |

## Notes

- All packages are built the same way with `uv build`.
- `platform` is a shortcut that releases all three packages (management,
  tool-runtime, cli).
- Publish credentials come from `.env` (local) or `deploy/ec2/.env.prod` (prod).
- Auto-bump appends `-git_sha` to avoid conflicts without manual version bumps.
