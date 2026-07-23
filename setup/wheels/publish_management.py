#!/usr/bin/env python3
"""Build, publish, and inventory the techneos-management wheel.

``techneos-management`` is the client/registration toolkit the catalog
``build_and_register.py`` scripts import. The platform publishes the
wheel here and records it in the ``compute_artifacts`` inventory
(``origin=platform``) so a standalone catalog checkout can resolve it.

Usage:
    uv run python setup/wheels/publish_management.py                 # build + publish + record
    uv run python setup/wheels/publish_management.py --env=prod      # publish to CodeArtifact + record
    uv run python setup/wheels/publish_management.py --skip-register # publish only (no inventory record)
"""

from __future__ import annotations

from pathlib import Path

from management.registration import (
    build_and_publish_wheel,
    load_env_file,
    make_publish_parser,
    publish_wheel_and_record,
    start_session,
)

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "packages" / "management"


def main() -> None:
    parser = make_publish_parser("Build, publish, and inventory the techneos-management wheel.")
    args = parser.parse_args()

    if args.skip_register:
        load_env_file(args.env)
        build_and_publish_wheel(PACKAGE_DIR, force=args.force)
        print("=== Published (not recorded — --skip-register) ===")
        return

    session = start_session(args)
    version = publish_wheel_and_record(session, PACKAGE_DIR, origin="platform", force=args.force)
    print(f"\n=== Done ===\n  Wheel: techneos-management=={version}")


if __name__ == "__main__":
    main()
