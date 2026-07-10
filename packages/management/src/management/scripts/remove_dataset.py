"""Remove a dataset (all versions) or a single dataset version.

Usage:
    ./bin/dataset_removal.sh <slug-or-uuid> [version] [options]

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --force         Cancel active dependent runs automatically

The gateway URL comes from ``PLATFORM_API_URL`` (set in the sourced
``.env.<env>``); ``--env`` selects the token cache (``~/.techneos/<env>_token.json``).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from management.auth import authenticate
from management.client import TechneOSClient
from management.dependencies import DependencyResult
from management.environment import resolve_environment
from management.registration import load_env_file
from management.resolve import resolve_resource


def _format_size(total_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if total_bytes < 1024:
            return f"{total_bytes:.1f} {unit}"
        total_bytes /= 1024
    return f"{total_bytes:.1f} TB"


def _strip_v(version: str) -> str:
    return version[1:] if version.startswith("v") else version


class DatasetRemovalScript:
    resource_type = "datasets"

    def run(self) -> None:
        # Parse arguments before anything else
        positional, rest = _split_args(sys.argv[1:])
        ref = positional[0] if len(positional) > 0 else None
        version_str = positional[1] if len(positional) > 1 else None
        dry_run = "--dry-run" in rest
        force = "--force" in rest
        env_arg = _parse_flag_value("--env", rest)

        if not ref:
            print(
                "Usage: dataset_removal.sh <slug-or-uuid> [version] [--env ENV] [--dry-run] [--force]",
                file=sys.stderr,
            )
            sys.exit(1)

        # Resolve target environment first — admin needs to see this immediately
        load_env_file(env_arg)
        self.env = resolve_environment(env_arg)
        print(f"Environment: {self.env}")
        print(flush=True)

        user = authenticate(self.env.api_url, env_name=self.env.name)
        print(f"Authenticated as {user.email} (role: {user.role})")
        print()

        client = TechneOSClient(api_url=self.env.api_url, token=user.token)

        dataset = resolve_resource(client, self.resource_type, ref)
        self._handle(client, dataset, version_str, dry_run, force)

    def _handle(
        self,
        client: TechneOSClient,
        dataset: dict[str, Any],
        version_str: str | None,
        dry_run: bool,
        force: bool,
    ) -> None:
        dataset_id = dataset["id"]
        dataset_name = dataset.get("name", "")
        dataset_slug = dataset.get("slug", "")

        versions = dataset.get("versions", [])
        if not versions:
            code, body = client.get(f"/api/v1/datasets/{dataset_id}")
            if code == 200:
                dataset = json.loads(body)
                versions = dataset.get("versions", [])

        version_count = len(versions)

        if version_str:
            version_num = int(_strip_v(version_str))
            version_info = next((v for v in versions if v.get("version") == version_num), None)
            if not version_info:
                print(
                    f"Error: Version {version_num} not found for dataset '{dataset_slug}'",
                    file=sys.stderr,
                )
                sys.exit(1)

            version_id = version_info["id"]
            version_status = version_info.get("status", "unknown")

            print(f"Dataset: {dataset_name} (slug: {dataset_slug})")
            print(f"Version: {version_num}  id={version_id}  status={version_status}")

            # Collect storage keys for this version
            storage_pairs = _extract_storage_keys(version_info)

            # Scan dependents
            dependents = self._scan_pipeline_references(
                client, dataset_id, dataset_slug, version_num=version_num
            )
            self._print_dependents(dependents)

            if dry_run:
                if storage_pairs:
                    print(f"\nWould delete {len(storage_pairs)} file(s) from MinIO")
                if dependents:
                    print(f"Would delete {len(dependents)} dependent pipeline run(s)")
                print("\nDRY RUN — no changes made.")
                return

            active = [d for d in dependents if d.active]
            if active and not force:
                self._confirm_or_exit(active)
            if active and force:
                self._cancel_active(client, active)

            # Delete MinIO files
            self._delete_minio_files(client, storage_pairs)

            # Delete version via API
            print(f"\nDeleting version {version_str}...")
            code, body = client.delete(f"/api/v1/datasets/{dataset_id}/versions/{version_id}")
            if code == 204:
                print(
                    f"Version {version_str} of '{dataset_name}' ({dataset_slug}) deleted successfully."
                )
            else:
                print(f"Error: Failed to delete version (HTTP {code}): {body}", file=sys.stderr)
                sys.exit(1)

            # Delete dependent pipeline runs
            self._delete_dependent_runs(client, dependents)
        else:
            # Entire dataset deletion
            all_storage_pairs: list[tuple[str, str]] = []
            total_size = 0
            for v in versions:
                all_storage_pairs.extend(_extract_storage_keys(v))
                files = v.get("files", [])
                if files:
                    total_size += sum(f.get("file_size", 0) for f in files)
                else:
                    total_size += v.get("file_size", 0)

            print(f"Dataset: {dataset_name} (slug: {dataset_slug})")
            print(f"Versions: {version_count}")
            print(f"Total size: {_format_size(total_size)}")

            # Scan dependents
            dependents = self._scan_pipeline_references(client, dataset_id, dataset_slug)
            self._print_dependents(dependents)

            if dry_run:
                if all_storage_pairs:
                    print(f"\nWould delete {len(all_storage_pairs)} file(s) from MinIO")
                if dependents:
                    print(f"Would delete {len(dependents)} dependent pipeline run(s)")
                print("\nDRY RUN — no changes made.")
                return

            active = [d for d in dependents if d.active]
            if active and not force:
                self._confirm_or_exit(active)
            if active and force:
                self._cancel_active(client, active)

            # Delete MinIO files
            self._delete_minio_files(client, all_storage_pairs)

            # Delete dataset via API
            print(f"\nDeleting dataset '{dataset_name}' ({dataset_slug})...")
            code, body = client.delete(f"/api/v1/datasets/{dataset_id}")
            if code == 204:
                print(f"Dataset '{dataset_name}' ({dataset_slug}) deleted successfully.")
            else:
                print(f"Error: Failed to delete dataset (HTTP {code}): {body}", file=sys.stderr)
                sys.exit(1)

            # Delete dependent pipeline runs
            self._delete_dependent_runs(client, dependents)

        print("\nDone.")

    def _scan_pipeline_references(
        self,
        client: TechneOSClient,
        dataset_id: str,
        dataset_slug: str,
        version_num: int | None = None,
    ) -> list[DependencyResult]:
        print("\nScanning for pipeline runs that reference this dataset...")
        dependents: list[DependencyResult] = []
        runs = client.paginate("/api/v1/pipeline-runs")

        for run in runs:
            params = run.get("parameters", {})
            param_str = json.dumps(params)
            run_id = run.get("id", "")
            run_name = run.get("name", "unnamed")
            run_status = run.get("status", "unknown")

            if version_num is not None:
                version_str = f"{dataset_slug}:v{version_num}"
                if version_str in param_str or (
                    f'"{dataset_slug}"' in param_str and f'"v{version_num}"' in param_str
                ):
                    is_active = run_status in ("pending", "running")
                    dependents.append(
                        DependencyResult("pipeline_run", run_id, run_name, run_status, is_active)
                    )
            else:
                if dataset_id in param_str or dataset_slug in param_str:
                    is_active = run_status in ("pending", "running")
                    dependents.append(
                        DependencyResult("pipeline_run", run_id, run_name, run_status, is_active)
                    )

        return dependents

    def _print_dependents(self, dependents: list[DependencyResult]) -> None:
        if not dependents:
            print("No pipeline runs reference this dataset.")
            return
        print(f"Found {len(dependents)} pipeline run(s) referencing this dataset:")
        for d in dependents:
            active_mark = " [ACTIVE]" if d.active else ""
            print(f"  - {d.name} ({d.status}) [{d.id_}]{active_mark}")

    def _confirm_or_exit(self, dependents: list[DependencyResult]) -> None:
        answer = (
            input(f"\n{len(dependents)} active dependent(s). Proceed with deletion? [y/N] ")
            .strip()
            .lower()
        )
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    def _cancel_active(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        for d in dependents:
            print(f"  Cancelling run '{d.name}' ({d.id_})...")
            code, body = client.post(f"/api/v1/pipeline-runs/{d.id_}/cancel")
            if code == 200:
                print("    Cancelled.")
            else:
                print(f"    Warning: Failed to cancel (HTTP {code}): {body}", file=sys.stderr)

    def _delete_minio_files(self, client: TechneOSClient, storage_pairs: list[tuple[str, str]]) -> None:
        if not storage_pairs:
            print("No files to delete.")
            return

        files = [{"bucket": b, "key": k} for b, k in storage_pairs]
        print(f"\nDeleting {len(storage_pairs)} file(s) via admin API...")

        code, body = client.delete_storage_files(files)
        if code != 200:
            print(f"Error: Failed to delete files (HTTP {code}): {body}", file=sys.stderr)
            sys.exit(1)

        result = json.loads(body)
        for path in result.get("deleted", []):
            print(f"  Deleted {path}")
        for err in result.get("errors", []):
            print(
                f"  Warning: Failed to delete {err['bucket']}/{err['key']}: {err['error']}",
                file=sys.stderr,
            )

    def _delete_dependent_runs(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        if not dependents:
            return
        print(f"\nDeleting {len(dependents)} dependent pipeline run(s)...")
        for d in dependents:
            code, body = client.delete(f"/api/v1/pipeline-runs/{d.id_}")
            if code == 204:
                print(f"  Deleted pipeline run '{d.name}' ({d.id_})")
            else:
                print(
                    f"  Warning: Failed to delete pipeline run '{d.name}' ({d.id_}): HTTP {code} {body}",
                    file=sys.stderr,
                )


def _extract_storage_keys(version_info: dict[str, Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    bucket = version_info.get("storage_bucket", "")
    files = version_info.get("files", [])
    if files:
        for f in files:
            sk = f.get("storage_key", "")
            if sk and bucket:
                pairs.append((bucket, sk))
    else:
        sk = version_info.get("storage_key", "")
        if sk and bucket:
            pairs.append((bucket, sk))
    return pairs


def _split_args(argv: list[str]) -> tuple[list[str], list[str]]:
    """Split argv into positional args and remaining flags.

    Handles ``--flag value`` pairs and ``--flag=value`` syntax.
    """
    positional: list[str] = []
    remaining: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            remaining.append(a)
            # Flags that take a value
            if a == "--env" and i + 1 < len(argv):
                remaining.append(argv[i + 1])
                i += 1
        else:
            positional.append(a)
        i += 1
    return positional, remaining


def _parse_flag_value(name: str, argv: list[str]) -> str | None:
    """Extract the value of a ``--key value`` or ``--key=value`` flag from remaining args."""
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            return argv[i + 1]
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return None


def main() -> None:
    DatasetRemovalScript().run()


if __name__ == "__main__":
    main()
