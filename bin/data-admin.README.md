# data-admin.sh

One tool to **back up**, **restore**, and **reset** the platform's stateful
stores, in either the local dev stack or the production EC2 deployment. It
replaces the old `bin/backup.sh` / `bin/restore.sh` / `bin/reset-data.sh`.

```
bin/data-admin.sh backup  [--env local|prod] [--dir <out>] [--keep N]
bin/data-admin.sh restore  --dir <backup>    [--env local|prod] [--yes]
bin/data-admin.sh reset   [--env local|prod] [--yes]
```

## What it manages

- **PostgreSQL** — the `techneos`, `keycloak`, and `airflow` databases. Keycloak
  is included on purpose: it owns the realms and SSO identities, so the
  `techneos` database alone doesn't describe who can log in.
- **MinIO** — the object-store bucket (`MINIO_BUCKET`, default `techneos-data`).
- **Valkey** — the cache RDB.

Credentials and the bucket name are read from **each container's own
environment** (`docker exec printenv`), never from your shell — so it never
assumes dev passwords and works the same against a production host.

## `--env local` vs `--env prod`

| | `--env local` (default) | `--env prod` |
|---|---|---|
| Acts on | your local Docker daemon | the EC2 host, over SSH+sudo (details from `deploy/ec2/.env.prod`) |
| App quiescing | **refuses** while dev services hold ports 8000–8008 (stop them with `make dev-stop`) | **stops the service containers** before, **restarts** them after — automatic |
| Backup lands | `./backups/<timestamp>/` on your workstation | `/data/techneos/backups/<ts>` **on the host** (survives redeploys) |

`make backup` / `make restore dir=…` / `make reset-data` are shortcuts for the
three `--env local` commands.

## Safety

- `restore` and `reset` are destructive. They require you to type the target name
  (`local` or `prod`) back before proceeding; `--yes` skips the prompt for
  non-interactive use. For `--env prod`, the confirmation happens on your
  workstation (naming the host) **before** anything is shipped or changed.
- `backup` exits non-zero and names what it missed if any component can't be
  captured. The `techneos` database is required; `keycloak`/`airflow`/MinIO/Valkey
  are skipped (not failed) when absent.

---

## Scenarios

### 1. Local — quick backup before risky work

```bash
bin/data-admin.sh backup            # → ./backups/<timestamp>/
# or: make backup
```

### 2. Local — reset to a clean slate

`reset` empties every store. Dev services hold open DB sessions that block the
drop, so stop them first, then rebuild the schema:

```bash
make dev-stop
bin/data-admin.sh reset --env local     # or: make reset-data
make migrate && make seed               # rebuild schema + defaults
make dev-all-portal
```

### 3. Local — restore from a backup

For an **exact** restore (target ends up matching the backup, no leftovers),
reset first — see [How restore behaves](#how-restore-behaves) for why:

```bash
make dev-stop
bin/data-admin.sh reset   --env local
bin/data-admin.sh restore --env local --dir ./backups/<timestamp>
make dev-all-portal
```

Skip the `reset` if you only want to overlay the backup onto the running data
(faster, but leaves anything not in the backup in place). No `migrate`/`seed` is
needed — `restore` recreates the schema from the dump.

### 4. Prod — back up before an upgrade

```bash
bin/data-admin.sh backup --env prod
```

The dump is written to `/data/techneos/backups/<ts>` **on the host** and left
there. `--keep N` prunes to the N most recent on-host backups (default 10; `0`
keeps all; or set `BACKUP_KEEP`). The host volume is not a disaster-recovery
target on its own — **copy a backup to S3** for off-host durability:

```bash
# on the host, or via ssh
aws s3 cp --recursive /data/techneos/backups/<ts> s3://<bucket>/techneos/<ts>/
```

### 5. Prod — restore / roll back

```bash
bin/data-admin.sh restore --env prod --dir <ts>     # a name under /data/techneos/backups
```

Run `restore --env prod` with **no `--dir`** to list the backups available on the
host. The script stops the service containers, restores all stores, restarts
keycloak/airflow, and starts the services back — no manual stop/start.

For an **exact** restore, reset first (both auto-quiesce the containers):

```bash
bin/data-admin.sh reset   --env prod
bin/data-admin.sh restore --env prod --dir <ts>
```

### 6. Prod — restore from a workstation / S3 copy

If `--dir` is a directory that exists on your workstation (e.g. one you pulled
from S3), it is uploaded to the host and restored from there:

```bash
aws s3 cp --recursive s3://<bucket>/techneos/<ts>/ ./restore-<ts>
bin/data-admin.sh restore --env prod --dir ./restore-<ts>
```

### 7. Prod — rebuild from scratch (no restore)

Resetting prod without restoring leaves the `techneos` database empty; rebuild
the schema and seed **in-container** by re-running the deploy (there is no
workstation `make` shortcut for prod migrate/seed):

```bash
bin/data-admin.sh reset --env prod
deploy/ec2/deploy.sh                 # runs migrate + seed in-container
```

---

## How restore behaves

`restore` is a per-store operation, **not** a wipe-then-load — the same in local
and prod:

- **Postgres** — `pg_restore --clean --if-exists` drops and recreates each object
  **that is in the dump**, then restores it. Tables in the backup are fully
  replaced; objects present in the target but **absent** from the dump (e.g. from
  a newer migration) are left untouched.
- **MinIO** — the backup's objects are copied **into** the bucket. Same-named
  objects are overwritten; objects already in the bucket that aren't in the
  backup **remain**. This is a merge.
- **Valkey** — the RDB is swapped wholesale, so the cache is fully replaced.

**To guarantee the target exactly matches the backup, run `reset` first, then
`restore`.** `reset` drops each database's schema (`DROP SCHEMA public CASCADE`)
and empties the bucket, so the restore lands on a genuinely empty target instead
of merging.

## Notes

- `backups/` is gitignored — those dumps are real user data.
- After a `reset`, keycloak re-imports its realm at startup when the realm is
  absent; airflow re-creates its own schema via its init.
