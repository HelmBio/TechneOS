# EC2 deployment

The whole platform on one EC2 instance: the nine backend services, the portal,
and their infrastructure (PostgreSQL, MinIO, Valkey, Keycloak, Airflow) in one
Docker Compose stack, fronted by nginx. Images are built elsewhere and pulled
from a registry; the instance runs no build.

```
your workstation                         the instance
──────────────                           ────────────
build-and-push.sh ──images──▶ registry ◀──── docker compose pull
deploy.sh ──bundle+ssh──▶ remote-deploy.sh ──▶ compose up · migrate · seed
```

## What's here

| File | Role |
|------|------|
| `docker-compose.prod.yml` | the full stack (127.0.0.1-bound; nginx is the only public edge) |
| `techneos.nginx.conf.template` | the edge config, rendered per-host at deploy time |
| `techneos-realm.keycloak.prod.json` | the Keycloak realm imported on first boot |
| `.env.prod.example` | the config + secrets template — copy, fill, keep out of git |
| `build-and-push.sh` | build the 11 images (linux/amd64) and push them, each tagged with its package version |
| `deploy.sh` | bundle + ship + run the deploy over SSH |
| `remote-deploy.sh` | host-side: pull, start, migrate, seed, configure nginx |
| `_image-catalog.sh` | the image catalog (name → manifest/version) shared by the two scripts, so their tags can't drift |

## AWS resources you provision

Provision these four yourself (this deploy assumes they exist), then record each
in `deploy/ec2/.env.prod`. Nothing here stores an access key — the
instance authenticates to ECR and CodeArtifact through its IAM role, and tokens
are minted from it per use.

| AWS resource | What it's for | `.env.prod` keys | Example value |
|--------------|---------------|------------------|---------------|
| **EC2 instance** | runs the whole stack | `SSH_HOST` (+ `SSH_USER`, `SSH_KEY_PATH`, `SSH_PORT`) | `ec2-1-2-3-4.compute.amazonaws.com` |
| **ECR registry** | holds the 11 platform images | `DOCKER_IMAGE_REGISTRY` (region auto-derived from its host) | `111122223333.dkr.ecr.us-east-1.amazonaws.com` |
| **ECR repos** `techneos/*` | one per image (gateway, the 8 services, portal, tool-runtime) | — (addressed as `$DOCKER_IMAGE_REGISTRY/techneos/<name>`; create the repos, no key) | `techneos/gateway`, `techneos/portal`, … |
| **CodeArtifact repo** | Python index for catalog tool/agent installs | `PYTHON_PACKAGE_INDEX_URL`, `PYTHON_PACKAGE_PUBLISH_URL` | `https://<domain>-<account>.d.codeartifact.<region>.amazonaws.com/pypi/<repo>/simple/` (index) and `…/pypi/<repo>/` (publish) |
| **IAM instance role** | ECR pull + CodeArtifact token minting, from the instance | — (attached to the instance; **not** an env var) | see policy below |

`DOCKER_IMAGE_REGISTRY` is the registry host with **no** repo path or trailing slash;
the images live under `$DOCKER_IMAGE_REGISTRY/techneos/<name>`, each tagged with its own
package version. For ECR the region is derived from that host, so you don't set
`AWS_REGION`; for a non-ECR registry set it to your region (defaults to
`us-east-1`). The two CodeArtifact URLs differ only by the trailing `simple/`:
the index URL (what the platform installs from) ends in `/simple/`; the publish
URL (what the catalog uploads to) does not.

The **IAM instance role** needs, at minimum:

```
ecr:GetAuthorizationToken, ecr:BatchGetImage, ecr:GetDownloadUrlForLayer
codeartifact:GetAuthorizationToken, codeartifact:ReadFromRepository, codeartifact:ListPackages
sts:GetServiceBearerToken
```

`codeartifact:ListPackages` backs the gateway's synthesized `/simple/` root
index (CodeArtifact doesn't serve the PEP 503 root listing); the read/token
actions cover the per-package pages and wheel downloads.

`PYTHON_PACKAGE_INDEX_URL` is a **credential-free base URL** — no token in the
file, nothing to rotate. The Airflow worker mints a CodeArtifact token from the
role at each install. Leave it blank to deploy without catalog content (the
platform still runs); fill it in once CodeArtifact is ready.

## Instance prerequisites

Beyond the AWS resources above, the instance itself needs:

- **Docker Engine + the compose plugin**, **nginx**, **certbot**, and the **AWS CLI**.
- A **`deploy` user** with your SSH public key and **passwordless sudo**
  (remote-deploy.sh configures nginx and owns `/data/techneos`). This is
  `SSH_USER` in `.env.prod`.
- DNS: the `PLATFORM_API_URL` and `PLATFORM_PORTAL_URL` hostnames resolving to
  the instance; ports 80/443 open.
- Size floor ≈ **8 vCPU / 32 GB**. With `COMPUTE_BACKEND=docker`, tool runs spawn
  containers on this same host beside everything else — that contention, not the
  platform, is the practical limit of a single instance.
- A **`/data` volume** with room for the databases and object store. The stack
  bind-mounts its state there — `/data/techneos/{postgres,minio,valkey}`, plus
  the code bundle under `/data/techneos/` — so it lands on the dedicated data
  disk rather than the root disk. `remote-deploy.sh` creates those dirs; size
  `/data` for your dataset and pipeline-artifact volume. Namespaced under
  `/data/techneos`, so it coexists with another deployment's `/data/<name>`.

## First deploy

```bash
# 1. one-time: the ECR repos and the CodeArtifact domain/repo (you provision these)

# 2. config — fill in every <placeholder>; keep this file out of git.
#    Set DEFAULT_ADMIN_* (don't ship the example admin) and DEFAULT_LLM_API_KEY
#    (seed uses it to provision the LLM provider the assistant runs on).
cp deploy/ec2/.env.prod.example deploy/ec2/.env.prod
$EDITOR deploy/ec2/.env.prod

# 3. build + push the images (needs registry credentials; not run on the instance)
deploy/ec2/build-and-push.sh          # tags each image with its package version

# 4. deploy — pins each service to its package version, ships it, brings it up:
deploy/ec2/deploy.sh
```

Both scripts first validate that the required `.env.prod` vars are filled — a
leftover `<placeholder>` is caught up front, not as an opaque failure mid-build
or on the host after the bundle+SSH round-trip.

Step 4 then does the whole deploy in one command: ship the bundle, bring the
stack up on the host, migrate, and seed — roles, org, admin, and (from
`DEFAULT_LLM_API_KEY`) the default LLM provider, all in-container from the
gateway image. Finally, from your workstation once the stack is up, it registers
the built-in Platform Assistant against that seeded provider. That last step runs
here rather than on the host because it drives the gateway API through the
`management` toolkit, which lives only in this checkout; it's skipped cleanly
when no provider was seeded (`DEFAULT_LLM_API_KEY` blank).
(`make register-platform-assistant` remains the way to run just that step by hand.)

The deploy is safe to re-run: migrations, the seed, and the registration are all
idempotent, and Keycloak imports its realm only when the realm is absent.

## Upgrades

Bump the `version` of each service you changed (its `pyproject.toml` /
`package.json`), then:

```bash
deploy/ec2/build-and-push.sh   # builds/pushes bumped versions; unchanged
                                        # ones are already published and skipped
deploy/ec2/deploy.sh           # pins each service to its current version
```

Only services whose version you bumped get a new image; the rest keep the tag
they're already on, so `up -d` recreates just those. Rebuilding *without* bumping
publishes an immutable `{version}-{rev}` image and warns — the deployable
`{version}` tag is left untouched, so the running deploy never changes under you
until you bump.

Roll back or hold back a single service by pinning its tag in `.env.prod`, e.g.
`AUTH_SERVICE_IMAGE_TAG=0.1.0` (or a specific `0.1.0-<rev>`); that override wins
over the auto-pinned version. Migrations run again on every deploy (idempotent).

## TLS

remote-deploy.sh obtains one Let's Encrypt cert covering both hosts via certbot's
webroot challenge, resolving the bootstrap ordering (nginx needs a cert to serve
:443; certbot needs :80 reachable to get one): it installs an HTTP-only config,
runs `certbot certonly`, then installs the full `:443` config. Set `CERTBOT_EMAIL`
in `.env.prod` to enable it. Left blank, the deploy stays HTTP-only until you
obtain a cert and re-run — the stack itself is unaffected.

## Security notes

- **`.env.prod` holds every production secret** and is gitignored under all its
  names. It never enters git; it travels to the host over SSH (renamed to `.env`)
  and lands as `/data/techneos/deploy/ec2/.env`, mode 600 — the file
  compose reads via `--env-file`.
- **Change the seeded admin.** With no `DEFAULT_ADMIN_*` overrides, the seed uses
  the example credentials (`admin@example.com` / `changeme123`). Set
  `DEFAULT_ADMIN_EMAIL` / `DEFAULT_ADMIN_PASSWORD` in `.env.prod` before the first
  deploy, or rotate immediately after.
- Every container port binds to `127.0.0.1`; nginx is the only thing listening
  on the public interface.

## Backups

Use `bin/data-admin.sh` from your workstation. `backup --env prod` ships the
script to the host over SSH+sudo and dumps every database and the object store
into `/data/techneos/backups/<ts>` **on the host** (reading the deployment's real
credentials from the containers). That directory is on the data volume, which
survives redeploys, so backups persist there; `--keep N` prunes to the N most
recent (default 10). Copy a backup to S3 for off-host durability.

`restore --env prod --dir <name>` restores an on-host backup in place (a name
under `/data/techneos/backups`, or an absolute path); pass a local directory
instead and it's uploaded first. Take a backup before every upgrade. Omit
`--env prod` to act on the local dev stack.
