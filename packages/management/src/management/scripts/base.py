from __future__ import annotations

import argparse
import sys
from typing import Any

from management.auth import authenticate
from management.client import TechneOSClient
from management.dependencies import DependencyResult
from management.environment import resolve_environment
from management.registration import load_env_file
from management.resolve import resolve_resource


class RemovalScript:
    resource_type: str = ""

    def run(self) -> None:
        parser = self._build_parser()
        args = parser.parse_args()

        env_arg = self._resolve_env_arg()
        load_env_file(env_arg)
        env = resolve_environment(env_arg)
        print(f"Environment: {env}")
        print(flush=True)

        user = authenticate(env.api_url, env_name=env.name)
        print(f"Authenticated as {user.email} (role: {user.role})")
        print()

        client = TechneOSClient(api_url=env.api_url, token=user.token)
        resource = resolve_resource(client, self.resource_type, args.ref)
        self._post_resolve(resource, client, args, env)

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(description=f"Remove a {self.resource_type.rstrip('s')}")
        parser.add_argument("ref", help=f"{self.resource_type.rstrip('s').title()} slug or UUID")
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without making changes",
        )
        parser.add_argument(
            "--force", action="store_true", help="Skip confirmation and cancel active dependents"
        )
        return parser

    def _resolve_env_arg(self) -> str | None:
        # Subclasses can override to extract --env from their own parser
        return None

    def _post_resolve(
        self, resource: dict[str, Any], client: TechneOSClient, args: argparse.Namespace, env: Any = None
    ) -> None:
        self.print_summary(resource)
        dependents = self.scan_dependencies(client, resource)
        self.report_dependents(dependents)

        if args.dry_run:
            print("\nDRY RUN — no changes made.")
            return

        active = [d for d in dependents if d.active]
        if active and not args.force:
            self.confirm_or_exit(active)
        if active and args.force:
            self.cancel_active(client, active)

        self.delete_resource(client, resource)
        self.cleanup_external(client, resource, env)

        print("\nDone.")

    def print_summary(self, resource: dict[str, Any]) -> None:
        raise NotImplementedError

    def scan_dependencies(
        self, client: TechneOSClient, resource: dict[str, Any]
    ) -> list[DependencyResult]:
        return []

    def report_dependents(self, dependents: list[DependencyResult]) -> None:
        if not dependents:
            print("No dependent resources found.")
            return
        print(f"Found {len(dependents)} dependent(s):")
        for d in dependents:
            active_mark = " [ACTIVE]" if d.active else ""
            print(f"  - {d.name} ({d.status}) [{d.id_}]{active_mark}")

    def cancel_active(self, client: TechneOSClient, dependents: list[DependencyResult]) -> None:
        pass

    def confirm_or_exit(self, dependents: list[DependencyResult]) -> None:
        answer = (
            input(f"\n{len(dependents)} active dependent(s). Proceed with deletion? [y/N] ")
            .strip()
            .lower()
        )
        if answer != "y":
            print("Aborted.")
            sys.exit(0)

    def delete_resource(self, client: TechneOSClient, resource: dict[str, Any]) -> None:
        code, body = client.delete(f"/api/v1/{self.resource_type}/{resource['id']}")
        if code == 204:
            label = self.resource_type.rstrip("s").title()
            print(f"{label} '{resource.get('name', resource['id'])}' deleted successfully.")
        else:
            print(f"Error: Failed to delete (HTTP {code}): {body}", file=sys.stderr)
            sys.exit(1)

    def cleanup_external(
        self, client: TechneOSClient, resource: dict[str, Any], env: Any = None
    ) -> None:
        pass
