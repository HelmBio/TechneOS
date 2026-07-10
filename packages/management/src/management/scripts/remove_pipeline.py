"""Remove a pipeline definition (all versions) or a single pipeline version.

Usage:
    ./bin/pipeline_removal.sh <slug-or-uuid> [version] [options]

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --force         Cancel active dependent runs automatically (no prompt)

The gateway URL comes from ``PLATFORM_API_URL`` (set in the sourced
``.env.<env>``); ``--env`` selects the token cache (``~/.techneos/<env>_token.json``).

What it does
------------
1. Resolve the pipeline by slug or UUID (both accepted).
2. Report its versions and any runs that reference them, flagging active runs.
3. Confirm (unless --force / --dry-run).
4. Delete each dependent run via ``DELETE /api/v1/pipeline-runs/{id}`` so the
   pipeline-service removes its MinIO objects (step outputs + inputs), then
   delete the definition:
   - Whole pipeline (no version given): ``DELETE /api/v1/pipelines/{id}``.
   - Single version (``v2`` or ``2`` given):
     ``DELETE /api/v1/pipelines/{id}/versions/{version_id}``.
   The definition delete cascades the remaining DB rows (PipelineVersion /
   PipelineRun / PipelineStepRun / PipelineRunArtifact) via ``ondelete=CASCADE``.

Examples:
    ./bin/pipeline_removal.sh hit-triage
    ./bin/pipeline_removal.sh hit-triage --dry-run
    ./bin/pipeline_removal.sh hit-triage v2
    ./bin/pipeline_removal.sh hit-triage v2 --dry-run
    ./bin/pipeline_removal.sh --env prod hit-triage v2 --force
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, cast

from management.auth import authenticate
from management.client import TechneOSClient
from management.environment import resolve_environment
from management.registration import load_env_file
from management.resolve import resolve_resource

ACTIVE_STATUSES = {"pending", "queued", "running"}


def _strip_v(version: str) -> str:
    return version[1:] if version.startswith("v") else version


class PipelineRemovalScript:
    resource_type = "pipelines"

    def run(self) -> None:
        args = self._build_parser().parse_args()

        load_env_file(args.env)

        env = resolve_environment(args.env)
        print(f"Environment: {env}")
        print(flush=True)

        user = authenticate(env.api_url, env_name=env.name)
        print(f"Authenticated as {user.email} (role: {user.role})")
        print()

        client = TechneOSClient(api_url=env.api_url, token=user.token)

        pipeline = resolve_resource(client, self.resource_type, args.ref)
        # resolve_resource may return a list-shaped record (no versions) when
        # matched by slug; re-fetch the full detail by id for the version list.
        pipeline = self._fetch_detail(client, pipeline)
        self._handle(client, pipeline, args.version, args.dry_run, args.force)

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Remove a pipeline definition (all versions) or a single version"
        )
        parser.add_argument("ref", help="Pipeline slug or UUID")
        parser.add_argument(
            "version",
            nargs="?",
            default=None,
            help="Specific version to remove (e.g. v2 or 2)",
        )
        parser.add_argument(
            "--env",
            help="Target environment (development, staging, production)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Cancel active dependent runs automatically (no prompt)",
        )
        return parser

    def _fetch_detail(self, client: TechneOSClient, pipeline: dict[str, Any]) -> dict[str, Any]:
        code, body = client.get(f"/api/v1/pipelines/{pipeline['id']}")
        if code == 200:
            try:
                return cast(dict[str, Any], json.loads(body))
            except json.JSONDecodeError:
                pass
        return pipeline

    def _handle(
        self,
        client: TechneOSClient,
        pipeline: dict[str, Any],
        version_str: str | None,
        dry_run: bool,
        force: bool,
    ) -> None:
        if version_str:
            self._handle_version(client, pipeline, version_str, dry_run, force)
        else:
            self._handle_pipeline(client, pipeline, dry_run, force)

    def _handle_version(
        self,
        client: TechneOSClient,
        pipeline: dict[str, Any],
        version_str: str,
        dry_run: bool,
        force: bool,
    ) -> None:
        pipeline_id = pipeline["id"]
        name = pipeline.get("name", "?")
        slug = pipeline.get("slug", "?")
        versions = pipeline.get("versions", [])

        version_num = int(_strip_v(version_str))
        version_info = next((v for v in versions if v.get("version") == version_num), None)
        if not version_info:
            print(
                f"Error: Version {version_num} not found for pipeline '{slug}'",
                file=sys.stderr,
            )
            sys.exit(1)

        version_id = version_info["id"]
        version_status = version_info.get("status", "unknown")

        print(f"Pipeline: {name} (slug: {slug})")
        print(f"Version: {version_num}  id={version_id}  status={version_status}")

        # Match only runs of this specific version (not the whole pipeline).
        runs = self._scan_runs(client, pipeline_id, {version_id}, match_pipeline=False)
        active = [r for r in runs if r["status"] in ACTIVE_STATUSES]
        self._report_runs(runs, active)

        if dry_run:
            print(f"\nWould delete version v{version_num} of '{slug}' and {len(runs)} run(s).")
            if runs:
                total_files = sum(self._count_pipeline_files(client, r["id"]) for r in runs)
                print(f"Would delete {total_files} MinIO file(s) across those run(s).")
            print("DRY RUN — no changes made.")
            return

        if active:
            if force:
                self._cancel_active(client, active)
            else:
                self._confirm_or_exit(active)

        self._delete_runs(client, runs)

        print(f"\nDeleting version v{version_num} of '{name}' ({slug})...")
        code, body = client.delete(f"/api/v1/pipelines/{pipeline_id}/versions/{version_id}")
        if code in (200, 204):
            print(
                f"Version v{version_num} of '{name}' ({slug}) deleted — "
                f"removed {len(runs)} run(s)."
            )
        else:
            print(f"Error: failed to delete version (HTTP {code}): {body}", file=sys.stderr)
            sys.exit(1)

        print("\nDone.")

    def _handle_pipeline(
        self,
        client: TechneOSClient,
        pipeline: dict[str, Any],
        dry_run: bool,
        force: bool,
    ) -> None:
        pipeline_id = pipeline["id"]
        name = pipeline.get("name", "?")
        slug = pipeline.get("slug", "?")
        versions = pipeline.get("versions", [])
        version_ids = {v.get("id") for v in versions if v.get("id")}

        print(f"Pipeline: {name} (slug: {slug})")
        print(f"  id:       {pipeline_id}")
        print(f"  versions: {len(versions)}")

        runs = self._scan_runs(client, pipeline_id, version_ids)
        active = [r for r in runs if r["status"] in ACTIVE_STATUSES]
        self._report_runs(runs, active)

        if dry_run:
            print(
                f"\nWould delete pipeline '{slug}', {len(versions)} version(s), "
                f"and {len(runs)} run(s)."
            )
            if runs:
                total_files = sum(self._count_pipeline_files(client, r["id"]) for r in runs)
                print(f"Would delete {total_files} MinIO file(s) across those run(s).")
            print("DRY RUN — no changes made.")
            return

        if active:
            if force:
                self._cancel_active(client, active)
            else:
                self._confirm_or_exit(active)

        self._delete_runs(client, runs)

        print(f"\nDeleting pipeline '{name}' ({slug})...")
        code, body = client.delete(f"/api/v1/pipelines/{pipeline_id}")
        if code in (200, 204):
            print(
                f"Pipeline '{name}' ({slug}) deleted — removed "
                f"{len(versions)} version(s) and {len(runs)} run(s)."
            )
        else:
            print(f"Error: failed to delete pipeline (HTTP {code}): {body}", file=sys.stderr)
            sys.exit(1)

        print("\nDone.")

    def _scan_runs(
        self,
        client: TechneOSClient,
        pipeline_id: str,
        version_ids: set[str],
        match_pipeline: bool = True,
    ) -> list[dict[str, Any]]:
        """Runs belonging to this pipeline (matched by pipeline_id or version_id).

        When ``match_pipeline`` is False, only runs whose ``version_id`` is in
        ``version_ids`` are matched — used to scope deletion to a single version.
        """
        print("  Pipeline runs...", end="", flush=True)
        found: list[dict[str, Any]] = []
        for run in client.paginate("/api/v1/pipeline-runs"):
            matched = run.get("version_id") in version_ids
            if match_pipeline and run.get("pipeline_id") == pipeline_id:
                matched = True
            if matched:
                found.append(
                    {
                        "id": run.get("id", ""),
                        "name": run.get("name") or (run.get("id", "")[:8]),
                        "status": run.get("status", "unknown"),
                    }
                )
        print(f" {len(found)} found")
        return found

    def _report_runs(self, runs: list[dict[str, Any]], active: list[dict[str, Any]]) -> None:
        if not runs:
            print("No runs reference this pipeline.")
            return
        print(f"Found {len(runs)} run(s) ({len(active)} active):")
        for r in runs:
            mark = " [ACTIVE]" if r["status"] in ACTIVE_STATUSES else ""
            print(f"  - {r['name']} ({r['status']}) [{r['id']}]{mark}")

    def _confirm_or_exit(self, active: list[dict[str, Any]]) -> None:
        answer = (
            input(f"\n{len(active)} active run(s) will be deleted. Proceed? [y/N] ").strip().lower()
        )
        if answer not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    def _cancel_active(self, client: TechneOSClient, active: list[dict[str, Any]]) -> None:
        print(f"\nCancelling {len(active)} active run(s)...")
        for r in active:
            code, body = client.post(f"/api/v1/pipeline-runs/{r['id']}/cancel")
            if code == 200:
                print(f"  Cancelled {r['name']} ({r['id']}).")
            else:
                print(
                    f"  Warning: failed to cancel {r['id']} (HTTP {code}): {body}",
                    file=sys.stderr,
                )

    def _count_pipeline_files(self, client: TechneOSClient, run_id: str) -> int:
        """Best-effort count of a run's MinIO files (inputs + step outputs).

        Both are PipelineRunArtifact rows, so they show up in the run
        detail's ``artifacts`` list regardless of ``io_type``.
        """
        code, body = client.get(f"/api/v1/pipeline-runs/{run_id}")
        if code != 200:
            return 0
        try:
            data = json.loads(body)
            return len(data.get("artifacts") or [])
        except (ValueError, AttributeError):
            return 0

    def _delete_runs(self, client: TechneOSClient, runs: list[dict[str, Any]]) -> None:
        """Delete each run individually so the service removes its MinIO files."""
        if not runs:
            return
        print(f"\nDeleting {len(runs)} run(s) (DB rows + MinIO files)...")
        for r in runs:
            n_files = self._count_pipeline_files(client, r["id"])
            code, body = client.delete(f"/api/v1/pipeline-runs/{r['id']}")
            if code in (200, 204):
                print(f"  Deleted run '{r['name']}' ({r['id']}) + {n_files} file(s)")
            else:
                print(
                    f"  Warning: failed to delete run {r['id']} (HTTP {code}): {body}",
                    file=sys.stderr,
                )


def main() -> None:
    PipelineRemovalScript().run()


if __name__ == "__main__":
    main()
