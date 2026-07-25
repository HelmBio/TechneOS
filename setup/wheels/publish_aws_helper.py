#!/usr/bin/env python3
"""Build, publish, and inventory the techneos-aws wheel.

``techneos-aws`` (module ``techneos_aws``) is the shared AWS primitives package
— ECR + CodeArtifact + a boto3 client factory. The platform services import it
in-workspace, but the Airflow worker (``packages/execution``) installs it as a
published wheel, so it needs to live on the index like the other platform wheels.

Usage:
    uv run python setup/wheels/publish_aws_helper.py                 # build + publish + record
    uv run python setup/wheels/publish_aws_helper.py --env=prod      # publish to CodeArtifact + record
    uv run python setup/wheels/publish_aws_helper.py --skip-register # publish only (no inventory record)
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

PACKAGE_DIR = Path(__file__).resolve().parents[2] / "packages" / "aws-helper"


def main() -> None:
    parser = make_publish_parser("Build, publish, and inventory the techneos-aws wheel.")
    args = parser.parse_args()

    if args.skip_register:
        load_env_file(args.env)
        build_and_publish_wheel(PACKAGE_DIR, force=args.force)
        print("=== Published (not recorded — --skip-register) ===")
        return

    session = start_session(args)
    version = publish_wheel_and_record(session, PACKAGE_DIR, origin="platform", force=args.force)
    print(f"\n=== Done ===\n  Wheel: techneos-aws=={version}")


if __name__ == "__main__":
    main()
