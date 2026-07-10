"""Remove a tool (all versions) or a single tool version.

Usage:
    ./bin/tool_removal.sh <slug-or-uuid> [version] [options]

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --force         Cancel active dependent runs automatically

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


def _strip_v(version: str) -> str:
    return version[1:] if version.startswith("v") else version


class ToolRemovalScript:
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
        self._handle(client, tool, args.version, args.dry_run, args.force)

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Remove a tool (all versions) or a single tool version"
        )
        parser.add_argument("ref", help="Tool slug or UUID")
        parser.add_argument(
            "version",
            nargs="?",
            default=None,
            help="Specific version to remove (e.g. v3 or 3)",
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
            help="Cancel active dependent runs automatically",
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
        if not versions:
            code, body = client.get(f"/api/v1/tools/{tool_id}")
            if code == 200:
                tool = json.loads(body)
                versions = tool.get("versions", [])

        version_count = len(versions)

        if version_str:
            self._handle_version(
                client,
                tool_id,
                tool_name,
                tool_slug,
                versions,
                version_str,
                dry_run,
                force,
            )
        else:
            self._handle_tool(
                client,
                tool_id,
                tool_name,
                tool_slug,
                versions,
                version_count,
                dry_run,
                force,
            )

    def _handle_version(
        self,
        client: TechneOSClient,
        tool_id: str,
        tool_name: str,
        tool_slug: str,
        versions: list[dict[str, Any]],
        version_str: str,
        dry_run: bool,
        force: bool,
    ) -> None:
        version_num = int(_strip_v(version_str))
        version_info = next((v for v in versions if v.get("version") == version_num), None)
        if not version_info:
            print(
                f"Error: Version {version_num} not found for tool '{tool_slug}'",
                file=sys.stderr,
            )
            sys.exit(1)

        version_id = version_info["id"]
        version_status = version_info.get("status", "unknown")

        print(f"Tool: {tool_name} (slug: {tool_slug})")
        print(f"Version: {version_num}  id={version_id}  status={version_status}")

        dependents = self._scan_pipeline_references(
            client,
            tool_id,
            tool_slug,
            version_num=version_num,
            version_id=version_id,
        )
        runs = [d for d in dependents if d.resource_type == "pipeline_run"]
        templates = [d for d in dependents if d.resource_type == "pipeline_version"]
        tool_runs = [d for d in dependents if d.resource_type == "tool_run"]
        self._print_dependents(runs, templates, tool_runs)

        if dry_run:
            if runs or templates or tool_runs:
                print(
                    f"Would delete {len(runs)} pipeline run(s), {len(templates)} pipeline version(s), and {len(tool_runs)} tool run(s)"
                )
                if tool_runs:
                    total_files = sum(self._count_tool_files(client, d.id_) for d in tool_runs)
                    print(f"Would delete {total_files} MinIO file(s) across those tool run(s)")
            print("\nDRY RUN \u2014 no changes made.")
            return

        active = [d for d in runs if d.active]
        if active and not force:
            self._confirm_or_exit(active)
        if active and force:
            self._cancel_active(client, active)

        self._delete_pipeline_versions(client, templates)
        self._delete_dependent_runs(client, runs)
        self._delete_tool_runs(client, tool_runs)

        print(f"\nDeleting version {version_str}...")
        code, body = client.delete(f"/api/v1/tools/{tool_id}/versions/{version_id}")
        if code == 204:
            print(f"Version {version_str} of '{tool_name}' ({tool_slug}) deleted successfully.")
        else:
            print(
                f"Error: Failed to delete version (HTTP {code}): {body}",
                file=sys.stderr,
            )
            sys.exit(1)

        print("\nDone.")

    def _handle_tool(
        self,
        client: TechneOSClient,
        tool_id: str,
        tool_name: str,
        tool_slug: str,
        versions: list[dict[str, Any]],
        version_count: int,
        dry_run: bool,
        force: bool,
    ) -> None:
        all_version_ids = {v.get("id", "") for v in versions if v.get("id")}

        print(f"Tool: {tool_name} (slug: {tool_slug})")
        print(f"Versions: {version_count}")

        dependents = self._scan_pipeline_references(
            client,
            tool_id,
            tool_slug,
            all_version_ids=all_version_ids,
        )
        runs = [d for d in dependents if d.resource_type == "pipeline_run"]
        templates = [d for d in dependents if d.resource_type == "pipeline_version"]
        tool_runs = [d for d in dependents if d.resource_type == "tool_run"]
        self._print_dependents(runs, templates, tool_runs)

        if dry_run:
            if runs or templates or tool_runs:
                print(
                    f"Would delete {len(runs)} pipeline run(s), {len(templates)} pipeline version(s), and {len(tool_runs)} tool run(s)"
                )
                if tool_runs:
                    total_files = sum(self._count_tool_files(client, d.id_) for d in tool_runs)
                    print(f"Would delete {total_files} MinIO file(s) across those tool run(s)")
            print("\nDRY RUN \u2014 no changes made.")
            return

        active = [d for d in runs if d.active]
        if active and not force:
            self._confirm_or_exit(active)
        if active and force:
            self._cancel_active(client, active)

        self._delete_pipeline_versions(client, templates)
        self._delete_dependent_runs(client, runs)
        self._delete_tool_runs(client, tool_runs)

        print(f"\nDeleting tool '{tool_name}' ({tool_slug})...")
        code, body = client.delete(f"/api/v1/tools/{tool_id}")
        if code == 204:
            print(f"Tool '{tool_name}' ({tool_slug}) deleted successfully.")
        else:
            print(
                f"Error: Failed to delete tool (HTTP {code}): {body}",
                file=sys.stderr,
            )
            sys.exit(1)

        print("\nDone.")

    def _scan_pipeline_references(
        self,
        client: TechneOSClient,
        tool_id: str,
        tool_slug: str,
        version_num: int | None = None,
        version_id: str | None = None,
        all_version_ids: set[str] | None = None,
    ) -> list[DependencyResult]:
        dependents: list[DependencyResult] = []

        # Scan pipeline runs (existing checks)
        dependents.extend(
            self._scan_pipeline_runs(
                client,
                tool_id,
                tool_slug,
                version_num,
                version_id,
                all_version_ids,
            )
        )

        # Scan pipeline version templates (steps JSONB with tool_slug + tool_version)
        dependents.extend(
            self._scan_pipeline_templates(
                client,
                tool_slug,
                version_num,
            )
        )

        # Scan tool runs (tool_version_id FK reference)
        dependents.extend(
            self._scan_tool_runs(
                client,
                version_id,
                all_version_ids,
            )
        )

        return dependents

    def _scan_pipeline_runs(
        self,
        client: TechneOSClient,
        tool_id: str,
        tool_slug: str,
        version_num: int | None = None,
        version_id: str | None = None,
        all_version_ids: set[str] | None = None,
    ) -> list[DependencyResult]:
        print("  Pipeline runs...", end="", flush=True)
        dependents: list[DependencyResult] = []
        runs = client.paginate("/api/v1/pipeline-runs")

        for run in runs:
            run_id = run.get("id", "")
            run_name = run.get("name", "unnamed")
            run_status = run.get("status", "unknown")
            is_active = run_status in ("pending", "running")
            params = run.get("parameters", {})
            param_str = json.dumps(params)

            matched = False

            # Check 1: parameters JSONB contains tool slug (and optionally version)
            if version_num is not None:
                if f'"{tool_slug}"' in param_str and f'"{version_num}"' in param_str:
                    matched = True
            else:
                if tool_slug in param_str or tool_id in param_str:
                    matched = True

            # Check 2: steps[].tool_version_id FK reference
            if not matched and version_id is not None:
                steps = run.get("steps", [])
                for step in steps:
                    if step.get("tool_version_id") == version_id:
                        matched = True
                        break

            if not matched and all_version_ids is not None:
                steps = run.get("steps", [])
                for step in steps:
                    tvid = step.get("tool_version_id", "")
                    if tvid in all_version_ids:
                        matched = True
                        break

            if matched:
                dependents.append(
                    DependencyResult("pipeline_run", run_id, run_name, run_status, is_active)
                )

        print(f" {len(dependents)} found")
        return dependents

    def _scan_pipeline_templates(
        self,
        client: TechneOSClient,
        tool_slug: str,
        version_num: int | None = None,
    ) -> list[DependencyResult]:
        print("  Pipeline version templates...", end="", flush=True)
        dependents: list[DependencyResult] = []
        pipelines = client.paginate("/api/v1/pipelines")

        for pipeline in pipelines:
            pipeline_id = pipeline.get("id")
            pipeline_name = pipeline.get("name", "unnamed")
            code, body = client.get(f"/api/v1/pipelines/{pipeline_id}/versions")
            if code != 200:
                continue
            versions = json.loads(body)
            if not isinstance(versions, list):
                continue
            for version in versions:
                version_id = version.get("id", "")
                version_label = version.get("version", "?")
                steps = version.get("steps", [])
                for step in steps:
                    if step.get("tool_slug") == tool_slug:
                        step_version = step.get("tool_version")
                        if version_num is not None and step_version != version_num:
                            continue
                        version_status = version.get("status", "unknown")
                        step_name = step.get("name", "unnamed")
                        dependents.append(
                            DependencyResult(
                                "pipeline_version",
                                version_id,
                                f"{pipeline_name}/{step_name}",
                                version_status,
                                active=False,
                                extra={
                                    "pipeline_name": pipeline_name,
                                    "pipeline_id": pipeline_id,
                                    "version_label": version_label,
                                    "step_name": step_name,
                                },
                            )
                        )

        print(f" {len(dependents)} found")
        return dependents

    def _scan_tool_runs(
        self,
        client: TechneOSClient,
        version_id: str | None = None,
        all_version_ids: set[str] | None = None,
    ) -> list[DependencyResult]:
        print("  Tool runs...", end="", flush=True)
        dependents: list[DependencyResult] = []
        runs = client.paginate("/api/v1/tool-runs")

        for run in runs:
            run_id = run.get("id", "")
            run_name = run.get("id", "")[:8]
            run_status = run.get("status", "unknown")
            is_active = run_status in ("pending", "running")
            tvid = run.get("tool_version_id", "")

            matched = (version_id is not None and tvid == version_id) or (
                all_version_ids is not None and tvid in all_version_ids
            )

            if matched:
                dependents.append(
                    DependencyResult("tool_run", run_id, run_name, run_status, is_active)
                )

        print(f" {len(dependents)} found")
        return dependents

    def _print_dependents(
        self,
        runs: list[DependencyResult],
        templates: list[DependencyResult],
        tool_runs: list[DependencyResult] | None = None,
    ) -> None:
        if not runs and not templates and not tool_runs:
            print("No pipeline runs, version templates, or tool runs reference this tool.")
            return

        if runs:
            print(f"Found {len(runs)} pipeline run(s) referencing this tool:")
            for d in runs:
                active_mark = " [ACTIVE]" if d.active else ""
                print(f"  - {d.name} ({d.status}) [{d.id_}]{active_mark}")

        if tool_runs:
            print(f"\nFound {len(tool_runs)} tool run(s) referencing this tool:")
            for d in tool_runs:
                active_mark = " [ACTIVE]" if d.active else ""
                print(f"  - {d.name} ({d.status}) [{d.id_}]{active_mark}")

        if templates:
            print(f"\nFound {len(templates)} pipeline version template(s) referencing this tool:")
            for d in templates:
                extra = d.extra
                pipeline_name = extra.get("pipeline_name", "?")
                version_label = extra.get("version_label", "?")
                step_name = extra.get("step_name", "?")
                print(f"  - {pipeline_name} v{version_label} / step '{step_name}' [{d.id_}]")

    def _confirm_or_exit(self, dependents: list[DependencyResult]) -> None:
        answer = (
            input(f"\n{len(dependents)} active dependent(s). Proceed with deletion? [y/N] ")
            .strip()
            .lower()
        )
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    def _delete_pipeline_versions(
        self, client: TechneOSClient, templates: list[DependencyResult]
    ) -> None:
        if not templates:
            return
        seen: set[str] = set()
        for d in templates:
            version_id = d.id_
            if version_id in seen:
                continue
            seen.add(version_id)
            pipeline_id = d.extra.get("pipeline_id", "")
            print(f"  Deleting pipeline version '{d.name}' ({version_id})...")
            code, body = client.delete(f"/api/v1/pipelines/{pipeline_id}/versions/{version_id}")
            if code == 204:
                print("    Deleted.")
            else:
                print(
                    f"    Warning: Failed to delete pipeline version (HTTP {code}): {body}",
                    file=sys.stderr,
                )

    def _cancel_active(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        for d in dependents:
            print(f"  Cancelling run '{d.name}' ({d.id_})...")
            code, body = client.post(f"/api/v1/pipeline-runs/{d.id_}/cancel")
            if code == 200:
                print("    Cancelled.")
            else:
                print(
                    f"    Warning: Failed to cancel (HTTP {code}): {body}",
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
                    f"  Warning: Failed to delete pipeline run "
                    f"'{d.name}' ({d.id_}): HTTP {code} {body}",
                    file=sys.stderr,
                )

    def _count_tool_files(self, client: TechneOSClient, run_id: str) -> int:
        """Best-effort count of a tool run's inputs + artifacts (from its detail)."""
        code, body = client.get(f"/api/v1/tool-runs/{run_id}")
        if code != 200:
            return 0
        try:
            data = json.loads(body)
            return len(data.get("inputs") or []) + len(data.get("artifacts") or [])
        except (ValueError, AttributeError):
            return 0

    def _delete_tool_runs(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        if not dependents:
            return
        print(f"\nDeleting {len(dependents)} dependent tool run(s) (DB rows + MinIO files)...")
        for d in dependents:
            n_files = self._count_tool_files(client, d.id_)
            code, body = client.delete(f"/api/v1/tool-runs/{d.id_}")
            if code == 204:
                print(f"  Deleted tool run ({d.id_}) + {n_files} file(s)")
            else:
                print(
                    f"  Warning: Failed to delete tool run ({d.id_}): HTTP {code} {body}",
                    file=sys.stderr,
                )


def main() -> None:
    ToolRemovalScript().run()


if __name__ == "__main__":
    main()
