"""Remove task runs AND the tool definition for a human task.

When a version argument is given, the task runs targeting that version
*and* the version record itself are deleted.  Without a version, *all*
task runs are removed first, then the tool (and all remaining versions)
are deleted as well.

Deleting a task run also removes its MinIO files (everything under
``task-runs/{slug}/v{N}/{run_id}/``) — handled server-side by the
``DELETE /api/v1/task-runs/{id}`` endpoint. ``--dry-run`` reports how many
files would be removed.

Usage:
    ./bin/task_removal.sh <task-slug-or-uuid> [version] [options]
    ./bin/task_removal.sh --env prod synthesis-request v3 --dry-run

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --force         Cancel active task runs automatically

The gateway URL comes from ``PLATFORM_API_URL`` (set in the sourced
``.env.<env>``); ``--env`` selects the token cache (``~/.techneos/<env>_token.json``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from management.auth import authenticate
from management.client import TechneOSClient
from management.dependencies import DependencyResult
from management.environment import resolve_environment
from management.registration import load_env_file
from management.resolve import resolve_resource

_ACTIVE_STATUSES = {"pending", "accepted", "in_progress"}


def _strip_v(version: str) -> str:
    return version[1:] if version.startswith("v") else version


class TaskRunRemovalScript:
    resource_type = "tools"

    def run(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args()

        load_env_file(args.env)

        self.env = resolve_environment(args.env)
        print(f"Environment: {self.env}")
        print(flush=True)

        user = authenticate(self.env.api_url, env_name=self.env.name)
        print(f"Authenticated as {user.email} (role: {user.role})")
        print()

        client = TechneOSClient(api_url=self.env.api_url, token=user.token)

        tool = resolve_resource(client, self.resource_type, args.ref)
        if tool.get("tool_type") != "human":
            print(
                f"Error: '{tool.get('slug', args.ref)}' is a "
                f"{tool.get('tool_type')!r} tool, not a human task. "
                "Use bin/tool_removal.sh to delete non-human tools.",
                file=sys.stderr,
            )
            sys.exit(1)

        self._handle(client, tool, args.version, args.dry_run, args.force)

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Remove task runs for a human task (all versions or a single version)"
        )
        parser.add_argument("ref", help="Task slug or UUID")
        parser.add_argument(
            "version",
            nargs="?",
            default=None,
            help="Limit deletion to runs against this version (e.g. v3 or 3)",
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
            help="Cancel active task runs automatically",
        )
        return parser

    def _handle(
        self,
        client: TechneOSClient,
        tool: dict[str, Any],
        version_str: str | None,
        dry_run: bool,
        force: bool,
    ) -> None:
        tool_id = tool["id"]
        tool_name = tool.get("name", "")
        tool_slug = tool.get("slug", "")
        versions = tool.get("versions", [])

        version_id: str | None = None
        version_num: int | None = None
        version_label = ""
        if version_str:
            version_num = int(_strip_v(version_str))
            match = next((v for v in versions if v.get("version") == version_num), None)
            if not match:
                print(
                    f"Error: Version {version_num} not found for task '{tool_slug}'",
                    file=sys.stderr,
                )
                sys.exit(1)
            version_id = match["id"]
            version_label = f" v{version_num}"

        print(f"Task: {tool_name} (slug: {tool_slug}){version_label}")

        version_num_by_id = {v["id"]: v.get("version") for v in versions if v.get("id")}
        task_runs = self._scan_task_runs(
            client,
            tool_id,
            version_id,
            version_num_by_id,
        )
        self._print_dependents(task_runs)

        if dry_run:
            if task_runs:
                active = [d for d in task_runs if d.active]
                print(f"Would delete {len(task_runs)} task run(s) ({len(active)} active)")
                total_files = sum(self._count_files(client, d.id_) for d in task_runs)
                print(f"Would delete {total_files} MinIO file(s) across those run(s)")
            if version_id:
                print(f"Would delete version{version_label} ({version_id})")
            else:
                for v in versions:
                    vn = v.get("version", "?")
                    print(f"Would delete tool version v{vn} ({v.get('id', '?')})")
                print(f"Would delete tool '{tool_name}' ({tool_slug})")
            print("\nDRY RUN — no changes made.")
            return

        if task_runs:
            active = [d for d in task_runs if d.active]
            if active and not force:
                self._confirm_or_exit(active)
            if active:
                self._cancel_active(client, active)
            self._delete_task_runs(client, task_runs)

        if version_id:
            self._delete_version(client, tool_id, version_id, version_label)
        else:
            self._delete_tool(client, tool_id, tool_name, tool_slug)

        print("\nDone.")

    def _scan_task_runs(
        self,
        client: TechneOSClient,
        tool_id: str,
        version_id: str | None,
        version_num_by_id: dict[str, int | None],
    ) -> list[DependencyResult]:
        print("  Task runs...", end="", flush=True)
        dependents: list[DependencyResult] = []
        runs = client.paginate("/api/v1/task-runs")

        for run in runs:
            run_tool_id = run.get("tool_id", "")
            run_version_id = run.get("tool_version_id", "")

            if version_id is not None:
                if run_version_id != version_id:
                    continue
            else:
                if run_tool_id != tool_id:
                    continue

            run_id = run.get("id", "")
            title = run.get("tool_name") or run_id[:8]
            status = run.get("status", "unknown")
            version_num = run.get("tool_version_num")
            if version_num is None:
                version_num = version_num_by_id.get(run_version_id)
            dependents.append(
                DependencyResult(
                    "task_run",
                    run_id,
                    title,
                    status,
                    active=status in _ACTIVE_STATUSES,
                    extra={"version": version_num},
                )
            )

        print(f" {len(dependents)} found")
        return dependents

    def _print_dependents(self, dependents: list[DependencyResult]) -> None:
        if not dependents:
            print("No task runs reference this task.")
            return
        print(f"Found {len(dependents)} task run(s):")
        for d in dependents:
            active_mark = " [ACTIVE]" if d.active else ""
            v = d.extra.get("version")
            version_label = f" v{v}" if v is not None else " v?"
            print(f"  -{version_label} {d.name} ({d.status}) [{d.id_}]{active_mark}")

    def _confirm_or_exit(self, dependents: list[DependencyResult]) -> None:
        answer = (
            input(f"\n{len(dependents)} active task run(s). Cancel and delete them? [y/N] ")
            .strip()
            .lower()
        )
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    def _cancel_active(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        print(f"\nCancelling {len(dependents)} active task run(s)...")
        for d in dependents:
            code, body = client.post(f"/api/v1/task-runs/{d.id_}/cancel")
            if code == 200:
                print(f"  Cancelled task run '{d.name}' ({d.id_})")
            else:
                print(
                    f"  Warning: Failed to cancel '{d.name}' ({d.id_}): HTTP {code} {body}",
                    file=sys.stderr,
                )

    def _count_files(self, client: TechneOSClient, run_id: str) -> int:
        """Best-effort count of a run's MinIO artifacts (from its detail)."""
        code, body = client.get(f"/api/v1/task-runs/{run_id}")
        if code != 200:
            return 0
        try:
            return len(json.loads(body).get("artifacts") or [])
        except (ValueError, AttributeError):
            return 0

    def _delete_task_runs(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        print(f"\nDeleting {len(dependents)} task run(s) (DB rows + MinIO files)...")
        for d in dependents:
            n_files = self._count_files(client, d.id_)
            code, body = client.delete(f"/api/v1/task-runs/{d.id_}")
            if code == 204:
                print(f"  Deleted task run '{d.name}' ({d.id_}) + {n_files} file(s)")
            else:
                print(
                    f"  Warning: Failed to delete '{d.name}' ({d.id_}): HTTP {code} {body}",
                    file=sys.stderr,
                )

    def _delete_version(
        self,
        client: TechneOSClient,
        tool_id: str,
        version_id: str,
        version_label: str,
    ) -> None:
        print(f"\nDeleting version{version_label} ({version_id})...")
        code, body = client.delete(f"/api/v1/tools/{tool_id}/versions/{version_id}")
        if code == 204:
            print(f"  Deleted version{version_label}")
        else:
            print(
                f"  Warning: Failed to delete version{version_label}: HTTP {code} {body}",
                file=sys.stderr,
            )

    def _delete_tool(
        self,
        client: TechneOSClient,
        tool_id: str,
        tool_name: str,
        tool_slug: str,
    ) -> None:
        print(f"\nDeleting tool '{tool_name}' ({tool_slug})...")
        code, body = client.delete(f"/api/v1/tools/{tool_id}")
        if code == 204:
            print(f"  Deleted tool '{tool_name}'")
        else:
            print(
                f"  Warning: Failed to delete tool '{tool_name}': HTTP {code} {body}",
                file=sys.stderr,
            )


def main() -> None:
    TaskRunRemovalScript().run()


if __name__ == "__main__":
    main()
