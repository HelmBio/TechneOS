"""Remove an AgentDefinition (and abort any active runs).

Usage:
    ./bin/agent_removal.sh <slug-or-uuid> [options]

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --yes, -y       Skip confirmation prompt

The gateway URL comes from ``PLATFORM_API_URL`` (set in the sourced
``.env.<env>``); ``--env`` selects the token cache (``~/.techneos/<env>_token.json``).

What it does
------------
1. Resolve the agent by slug or UUID (both accepted).
2. Print summary: name, slug, id, framework, model provider, and the
   ``package_config`` (if any).
3. Report any active runs / tasks attached to this agent.
4. Confirm (unless --yes / --dry-run).
5. Call ``DELETE /api/v1/agents/{id}``, which the agent-service
   cascade-deletes through AgenticRun / AgenticTask records.

What it does NOT do
-------------------
- Remove the agent's wheel from the Python package index. Index
  retention policies handle stale versions.
- `pip uninstall` the package from the running agent-service. A
  service restart will skip the install for the deleted row, but the
  in-memory copy lingers until then.
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


class AgentRemovalScript:
    resource_type = "agents"

    def run(self) -> None:
        positional, rest = _split_args(sys.argv[1:])
        ref = positional[0] if positional else None
        dry_run = "--dry-run" in rest
        yes = "--yes" in rest or "-y" in rest
        env_arg = _parse_flag_value("--env", rest)

        if not ref:
            print(
                "Usage: agent_removal.sh <slug-or-uuid> [--env ENV] [--dry-run] [--yes]",
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
        # Agents listing excludes platform agents by default — pass the flag
        # so we can target platform-assistant-style agents too if needed.
        agent = resolve_resource(client, self.resource_type, ref)

        self._print_summary(agent)
        runs, total_runs = self._scan_runs(client, agent)
        active_runs, completed_runs = self._partition_runs(runs)
        total_tasks = self._scan_task_total(client, agent)
        self._report_runs(active_runs, completed_runs, runs, total_runs, total_tasks)

        if dry_run:
            print("\nDRY RUN — no changes made.")
            return

        if not yes:
            cascade_summary = self._cascade_summary(
                total_runs, len(active_runs), len(completed_runs), total_tasks
            )
            prompt = (
                f"\nDelete agent '{agent.get('slug', '?')}' ({agent['id']}) from "
                f"{env.api_url}?\n"
                f"  This deletes the DB row and cascades to:\n"
                f"{cascade_summary}"
                f"  Continue? [y/N] "
            )
            answer = input(prompt).strip().lower()
            if answer not in ("y", "yes"):
                print("Aborted.")
                return

        print(f"\nDeleting {agent['id']} ...")
        code, body = client.delete(f"/api/v1/agents/{agent['id']}")
        if code not in (200, 204):
            print(f"Error: delete failed (HTTP {code}): {body}", file=sys.stderr)
            sys.exit(1)

        print(f"  Deleted agent '{agent.get('name', agent['id'])}'.")
        if agent.get("package_config"):
            print(
                "  Note: the wheel on the package index is unchanged. The agent-service "
                "skips the install for this row on next restart, but the already-installed "
                "copy lingers in-process until then."
            )
        print("\nDone.")

    def _print_summary(self, agent: dict[str, Any]) -> None:
        print(f"Agent:         {agent.get('name', '?')}")
        print(f"  id:          {agent['id']}")
        print(f"  slug:        {agent.get('slug', '?')}")
        print(f"  framework:   {agent.get('framework', '?')}")
        model_cfg = agent.get("model_config") or {}
        if model_cfg:
            provider = model_cfg.get("provider", "?")
            model = model_cfg.get("model", "?")
            print(f"  model:       {provider} / {model}")
        pkg = agent.get("package_config") or {}
        if pkg:
            print(
                f"  package:     {pkg.get('name', '?')}=={pkg.get('version', '?')} "
                f"(entry_point: {pkg.get('entry_point', '?')})"
            )
        else:
            print("  package:     (none — code-baked, legacy path)")

    def _scan_runs(
        self, client: TechneOSClient, agent: dict[str, Any]
    ) -> tuple[list[dict[str, Any]], int]:
        """Fetch up to one page of runs attached to this agent (any status).

        Returns ``(items, total)`` where ``items`` is the first page (used for
        the summary listing) and ``total`` is the authoritative count from
        the API's PaginatedResponse — needed because the summary listing is
        capped to keep the prompt readable. Returns ``([], 0)`` if the
        endpoint isn't reachable.
        """
        code, body = client.get(f"/api/v1/agentic-runs?agent_id={agent['id']}&limit=200")
        if code != 200:
            return [], 0
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return [], 0
        items = data.get("items", data if isinstance(data, list) else [])
        total = int(data.get("total", len(items)))
        return items, total

    def _scan_task_total(self, client: TechneOSClient, agent: dict[str, Any]) -> int:
        """Return the authoritative task count for this agent.

        Queries the tasks endpoint directly (rather than summing task_count
        across runs) so orphan tasks — those with an agent_id but no
        agentic_run_id — are counted too. They'd cascade-delete via the
        AgentDefinition.tasks relationship, so the user deserves to know
        they exist.
        """
        code, body = client.get(f"/api/v1/agentic-tasks?agent_id={agent['id']}&limit=1")
        if code != 200:
            return 0
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return 0
        return int(data.get("total", 0))

    @staticmethod
    def _partition_runs(
        runs: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split runs by terminal status. ``latest_task_status`` of ``pending``
        or ``running`` is active; anything else (``completed``/``failed``/
        ``cancelled``/None) is terminal.
        """
        active_statuses = {"pending", "running"}
        active: list[dict[str, Any]] = []
        completed: list[dict[str, Any]] = []
        for r in runs:
            status = r.get("latest_task_status")
            if status in active_statuses:
                active.append(r)
            else:
                completed.append(r)
        return active, completed

    def _report_runs(
        self,
        active: list[dict[str, Any]],
        completed: list[dict[str, Any]],
        sample_runs: list[dict[str, Any]],
        total_runs: int,
        total_tasks: int,
    ) -> None:
        if total_runs == 0 and total_tasks == 0:
            print("No runs or tasks attached to this agent.")
            return
        page_note = ""
        if len(sample_runs) < total_runs:
            page_note = f"  (showing first {len(sample_runs)} of {total_runs} runs)"
        print(
            f"Runs: {total_runs} ({len(active)} active, {len(completed)} completed). "
            f"Tasks: {total_tasks}.{page_note}"
        )
        if active:
            print("Active runs:")
            for r in active:
                self._print_run_line(r)
        if completed:
            # Don't dump every completed run for chatty agents — show the
            # first few plus a count of the rest. Keeps the summary readable
            # for agents with months of run history.
            print("Completed runs:")
            shown = completed[:5]
            for r in shown:
                self._print_run_line(r)
            if len(completed) > len(shown):
                print(f"  ... and {len(completed) - len(shown)} more.")

    @staticmethod
    def _print_run_line(r: dict[str, Any]) -> None:
        title = r.get("title") or "(untitled)"
        tasks = r.get("task_count", 0)
        status = r.get("latest_task_status") or "(no tasks)"
        print(f"  - {r.get('id', '?')}  title={title!r}  status={status}  tasks={tasks}")

    @staticmethod
    def _cascade_summary(
        total_runs: int,
        active_count: int,
        completed_count: int,
        total_tasks: int,
    ) -> str:
        """One-line-per-resource cascade preview for the confirmation prompt."""
        lines = []
        if total_runs:
            lines.append(
                f"    {total_runs} AgenticRun row(s) "
                f"({active_count} active, {completed_count} completed)"
            )
        if total_tasks:
            lines.append(f"    {total_tasks} AgenticTask row(s)")
        if not lines:
            lines.append("    (no dependent runs or tasks)")
        return "\n".join(lines) + "\n"


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
    AgentRemovalScript().run()


if __name__ == "__main__":
    main()
