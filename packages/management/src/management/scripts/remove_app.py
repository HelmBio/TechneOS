"""Remove an App (and stop its embedded container if running).

Usage:
    ./bin/app_removal.sh <slug-or-uuid> [options]

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --yes, -y       Skip confirmation prompt

The gateway URL comes from ``PLATFORM_API_URL`` (set in the sourced
``.env.<env>``); ``--env`` selects the token cache (``~/.techneos/<env>_token.json``).

What it does
------------
1. Resolve the App by slug or UUID (both accepted).
2. Print summary: name, slug, id, launch_mode, runtime_status, and the
   count of AppLaunch audit rows that will cascade-delete (every launch
   ever recorded for this app — AppLaunch has no ``status`` field, it's
   a one-shot audit record).
3. Confirm (unless --yes / --dry-run).
4. Call DELETE /api/v1/apps/{id}, which the app-service handles by
   enqueueing a container stop (for embedded apps) and dropping the row.
   The FK ``ondelete="CASCADE"`` on app_launches.app_id removes every
   audit row automatically.

What it does NOT do
-------------------
- Remove the Docker image from the registry. Image lifecycle is a
  deployment concern; ECR retention policies handle stale tags.
- Remove the image from the platform host's local docker cache. Use
  ``docker image prune`` for that.
- Cascade-delete AppLaunch records explicitly — the FK cascade handles
  it as part of the App row deletion.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from management.auth import authenticate
from management.client import TechneOSClient
from management.environment import resolve_environment
from management.registration import load_env_file
from management.resolve import resolve_resource


class AppRemovalScript:
    resource_type = "apps"

    def run(self) -> None:
        positional, rest = _split_args(sys.argv[1:])
        ref = positional[0] if positional else None
        dry_run = "--dry-run" in rest
        yes = "--yes" in rest or "-y" in rest
        env_arg = _parse_flag_value("--env", rest)

        if not ref:
            print(
                "Usage: app_removal.sh <slug-or-uuid> [--env ENV] [--dry-run] [--yes]",
                file=sys.stderr,
            )
            sys.exit(1)

        load_env_file(env_arg)

        env = resolve_environment(env_arg)
        print(f"Environment: {env}")
        print(flush=True)

        user = authenticate(env.api_url, env_name=env.name)
        print(f"Authenticated as {user.email} (role: {user.role})")
        print()

        client = TechneOSClient(api_url=env.api_url, token=user.token)
        app = resolve_resource(client, self.resource_type, ref)

        self._print_summary(app)
        launch_sample, total_launches = self._scan_launches(client, app)
        self._report_launches(launch_sample, total_launches)

        if dry_run:
            print("\nDRY RUN — no changes made.")
            return

        if not yes:
            prompt_lines = [
                f"\nDelete app '{app.get('slug', '?')}' ({app['id']}) from {env.api_url}?",
                "  This deletes the DB row and cascades to:",
            ]
            if app.get("launch_mode") == "embedded":
                prompt_lines.append(
                    "    the running container (stopped and removed by the app-service deployer)"
                )
            if total_launches:
                prompt_lines.append(f"    {total_launches} AppLaunch audit row(s)")
            if not total_launches and app.get("launch_mode") != "embedded":
                prompt_lines.append("    (no dependent rows)")
            prompt_lines.append("  Continue? [y/N] ")
            answer = input("\n".join(prompt_lines)).strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted.")
                return

        print(f"\nDeleting {app['id']} ...")
        code, body = client.delete(f"/api/v1/apps/{app['id']}")
        if code not in (200, 204):
            print(f"Error: delete failed (HTTP {code}): {body}", file=sys.stderr)
            sys.exit(1)

        print(f"  Deleted app '{app.get('name', app['id'])}'.")
        if app.get("launch_mode") == "embedded":
            print("  The app-service deployer will stop and remove the container if running.")
        print("\nDone.")

    def _print_summary(self, app: dict[str, Any]) -> None:
        print(f"App:           {app.get('name', '?')}")
        print(f"  id:          {app['id']}")
        print(f"  slug:        {app.get('slug', '?')}")
        print(f"  launch_mode: {app.get('launch_mode', '?')}")
        runtime = app.get("runtime_status")
        if runtime:
            print(f"  runtime:     {runtime}")
        if app.get("docker_image"):
            print(f"  image:       {app['docker_image']}:{app.get('docker_tag', 'latest')}")

    def _scan_launches(
        self, client: TechneOSClient, app: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """Return (sample_items, total_count) for AppLaunch audit rows.

        AppLaunch is a one-shot audit record (no ``status`` column — that
        was a fiction in an earlier version of this script). Every row
        cascade-deletes with the App via the ``ondelete="CASCADE"`` FK,
        so the user deserves to know how many there are before saying y.
        Returns ``([], 0)`` if the endpoint isn't reachable.
        """
        code, body = client.get(f"/api/v1/apps/{app['id']}/launches?limit=100")
        if code != 200:
            return [], 0
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return [], 0
        items = data.get("items", data if isinstance(data, list) else [])
        total = int(data.get("total", len(items)))
        return items, total

    def _report_launches(self, sample: list[dict[str, Any]], total: int) -> None:
        if total == 0:
            print("No launches recorded for this app.")
            return
        note = ""
        if len(sample) < total:
            note = f"  (showing first {len(sample)} of {total})"
        print(f"Launch audit rows: {total}.{note}")
        # Don't dump every launch for popular apps — show first 5 plus a
        # tail count. Each line: id, who launched it, when.
        shown = sample[:5]
        for launch in shown:
            user = (
                launch.get("launcher_name")
                or launch.get("user_email")
                or launch.get("launched_by")
                or "?"
            )
            when = launch.get("created_at") or launch.get("started_at") or "?"
            print(f"  - {launch.get('id', '?')}  user={user}  at={when}")
        if total > len(shown):
            print(f"  ... and {total - len(shown)} more.")


def _split_args(argv: list[str]) -> tuple[list[str], list[str]]:
    positional: list[str] = []
    remaining: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            remaining.append(a)
            if a == "--env" and i + 1 < len(argv):
                remaining.append(argv[i + 1])
                i += 1
        elif a in ("-y",):
            remaining.append(a)
        else:
            positional.append(a)
        i += 1
    return positional, remaining


def _parse_flag_value(name: str, argv: list[str]) -> str | None:
    for i, arg in enumerate(argv):
        if arg == name and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            return argv[i + 1]
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return None


def main() -> None:
    AppRemovalScript().run()


if __name__ == "__main__":
    main()
