"""Remove a local user and all associated data.

Usage:
    ./bin/user_removal.sh <email> [options]

Options:
    --env ENV       Target environment (development, staging, production)
    --dry-run       Show what would be deleted without making changes
    --yes           Skip confirmation prompt

The gateway URL comes from ``PLATFORM_API_URL`` (set in the sourced
``.env.<env>``); ``--env`` selects the token cache (``~/.techneos/<env>_token.json``).
"""

from __future__ import annotations

import json
import sys

from management.auth import authenticate
from management.client import TechneOSClient
from management.environment import resolve_environment
from management.registration import load_env_file


def _render_dependents(dependents: dict[str, int]) -> str:
    lines = []
    for label, count in sorted(dependents.items()):
        if count:
            lines.append(f"  {label}: {count} row(s)")
    return "\n".join(lines) if lines else "  (none)"


class UserRemovalScript:
    def run(self) -> None:
        positional, rest = _split_args(sys.argv[1:])
        email = positional[0] if len(positional) > 0 else None
        dry_run = "--dry-run" in rest
        yes = "--yes" in rest or "-y" in rest
        env_arg = _parse_flag_value("--env", rest)

        if not email:
            print("Usage: user_removal.sh <email> [--env ENV] [--dry-run] [--yes]", file=sys.stderr)
            sys.exit(1)

        load_env_file(env_arg)

        self.env = resolve_environment(env_arg)
        print(f"Environment: {self.env}")
        print(flush=True)

        user = authenticate(self.env.api_url, env_name=self.env.name)
        print(f"Authenticated as {user.email} (role: {user.role})")
        print()

        client = TechneOSClient(api_url=self.env.api_url, token=user.token)

        self._handle(client, email, dry_run, yes)

    def _handle(
        self,
        client: TechneOSClient,
        email: str,
        dry_run: bool,
        yes: bool,
    ) -> None:
        print(f"=== Dry-run preview for user: {email} ===\n")

        code, body = client.delete(f"/api/v1/admin/users/by-email/{_urlencode(email)}?dry_run=true")

        if code != 200:
            self._print_error(code, body)
            sys.exit(1)

        data = json.loads(body)
        user_info = data.get("user", {})
        dependents = data.get("dependents", {})
        total = data.get("total_dependents", 0)

        print(
            f"User: {user_info.get('email', email)}  id={user_info.get('id', '?')}  org_id={user_info.get('org_id', '?')}"
        )
        print(f"Auth: {user_info.get('auth_method', '?')}")
        print()

        print(_render_dependents(dependents))
        print()
        print(f"  TOTAL related rows: {total}")
        print("  + 1 user row")
        print()

        if dry_run:
            print("DRY RUN — no changes made.")
            return

        if not yes:
            answer = input("Proceed with deletion? [y/N] ").strip().lower()
            if answer != "y":
                print("Aborted.")
                return

        print("=== Deleting ===\n")

        code, body = client.delete(f"/api/v1/admin/users/by-email/{_urlencode(email)}")

        if code != 200:
            self._print_error(code, body)
            sys.exit(1)

        data = json.loads(body)
        dependents = data.get("dependents", {})
        total = data.get("total_dependents", 0)

        print(_render_dependents(dependents))
        print(f"  Deleted {total} dependent row(s)")
        print(f"  Deleted user {email}")

        print("\nDone.")

    def _print_error(self, code: int, body: str) -> None:
        try:
            detail = json.loads(body).get("detail", body)
        except (json.JSONDecodeError, AttributeError):
            detail = body
        print(f"Error (HTTP {code}): {detail}", file=sys.stderr)


def _urlencode(value: str) -> str:
    """Minimal URL-encoding for email addresses in path segments."""
    return value.replace("@", "%40")


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
    UserRemovalScript().run()


if __name__ == "__main__":
    main()
