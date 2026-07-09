#!/usr/bin/env python3
"""Build the techneos/tool-runtime image and record it in the artifact inventory.

The single ``techneos/tool-runtime`` image is the TechneOS tool execution runtime: the
Airflow worker runs it for pypi-type tools and container-type tools build
``FROM`` it. Unlike a catalog tool this image backs no Tool /
ToolVersion row — so this script only builds (and, for prod, pushes) the image,
then records it in ``compute_artifacts`` (origin ``platform``) so the
platform has a complete inventory of what's published.

The version is the single source of truth in ``[project].version`` of
``pyproject.toml``; the image is tagged ``:{version}`` and ``:latest``.

The wheel (``techneos-tool-runtime``) is what catalog packages depend on; with
``--publish-wheel`` this script also builds and publishes it to the package
index and records it as a ``kind=wheel`` artifact, so a catalog repo split out of
the monorepo can resolve the dependency.

Usage:
    uv run python packages/tool-runtime/build_and_register.py                 # build (local) + record image
    uv run python packages/tool-runtime/build_and_register.py --skip-register # build only (old build.sh)
    uv run python packages/tool-runtime/build_and_register.py --env=prod      # buildx + push to ECR + record
    uv run python packages/tool-runtime/build_and_register.py --skip-build    # record an already-built image
    uv run python packages/tool-runtime/build_and_register.py --publish-wheel # also publish + record the wheel
"""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path

from management.registration import (
    add_auth_args,
    add_env_arg,
    auth_headers,
    authenticate,
    build_and_publish_wheel,
    build_and_push_image,
    ecr_login,
    ensure_ecr_repo,
    load_env_file,
    pull_tool_image_on_ec2,
    record_artifact,
    resolve_api_url,
    resolve_ecr_registry,
    resolve_image_repo,
)

PACKAGE_DIR = Path(__file__).parent
IMAGE = "techneos/tool-runtime"


def _pyproject() -> dict:
    return tomllib.loads((PACKAGE_DIR / "pyproject.toml").read_text())


def _get_version() -> str:
    """Read [project].version from pyproject.toml (single source of truth)."""
    return str(_pyproject()["project"]["version"])


# Distribution name of the wheel — what catalog packages depend on.
PACKAGE_NAME = str(_pyproject()["project"]["name"])  # "techneos-tool-runtime"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the techneos/tool-runtime image and record it in the artifact inventory.",
    )
    add_env_arg(parser)
    add_auth_args(parser)
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip the docker build (record an already-built/pushed image)",
    )
    parser.add_argument(
        "--skip-push",
        action="store_true",
        help="Build but do not push to ECR (prod only; local never pushes)",
    )
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Build only — do not record the image in the artifact inventory",
    )
    parser.add_argument(
        "--publish-wheel",
        action="store_true",
        help="Also build + publish the techneos-tool-runtime wheel to the package index "
        "(so a split-out catalog repo can resolve the dep) and record it",
    )
    args = parser.parse_args()

    load_env_file(args.env)

    version = _get_version()
    # Env-aware coordinates, same convention as the catalog container tools:
    # for prod this is the full ECR URL (the host's credential helper pulls it);
    # for local it is the bare techneos/tool-runtime in the shared daemon. IMAGE stays
    # bare for build_and_push_image, which prefixes the registry itself.
    image_ref = f"{resolve_image_repo(args.env)}/tool-runtime"
    # Local runs use the same Docker daemon as the worker — no registry push.
    do_push = not args.skip_push and not args.skip_build and args.env != "local"

    print(f"=== techneos/tool-runtime {version} ({args.env}) ===")
    print(f"  Image:    {image_ref}:{version}")
    print(f"  Build:    {not args.skip_build}")
    print(f"  Push:     {do_push}" + ("  (skipped for local)" if args.env == "local" else ""))
    print(f"  Wheel:    {args.publish_wheel}")
    print(f"  Register: {not args.skip_register}")
    print()

    # Authenticate up front (like the catalog scripts) so a bad credential fails
    # before the build, not after. Skipped entirely with --skip-register.
    api_url = resolve_api_url(args.env)
    headers = None
    if not args.skip_register:
        token = authenticate(api_url, args.env, args.email, args.password)
        headers = auth_headers(token)
        print(f"  API URL:  {api_url}")
        print()

    if not args.skip_build:
        print("=== Build" + (" & push image" if do_push else " image") + " ===")
        if do_push:
            ecr_login(args.env)
            ensure_ecr_repo(args.env, IMAGE)
        build_and_push_image(IMAGE, PACKAGE_DIR, version, args.env, push=do_push)
        if do_push:
            print("=== Pre-cache image on EC2 ===")
            pull_tool_image_on_ec2(args.env, ecr_image=image_ref, version=version)
        print()

    # Publishing the wheel uses index credentials, not the platform JWT, so it
    # runs even under --skip-register (it just won't be recorded then).
    wheel_publish_url = None
    if args.publish_wheel:
        print("=== Build & publish wheel ===")
        wheel_publish_url = build_and_publish_wheel(PACKAGE_DIR)
        print()

    if args.skip_register:
        print("=== Skipping inventory registration (--skip-register) ===")
        return

    print("=== Recording image in the artifact inventory ===")
    # Record the bare repo + separate registry_url (same convention as the
    # platform images in deploy/build-and-push.sh) so the manual and CI paths
    # upsert the same inventory row. Catalog tools instead store the env-aware
    # image_ref because their ToolVersion.docker_image must match for validation;
    # the runtime image backs no ToolVersion, so the bare form is unambiguous.
    record_artifact(
        api_url,
        headers,
        kind="docker_image",
        origin="platform",
        name=IMAGE,
        version=version,
        registry_url=resolve_ecr_registry(args.env),
    )

    if args.publish_wheel:
        print("=== Recording wheel in the artifact inventory ===")
        record_artifact(
            api_url,
            headers,
            kind="wheel",
            origin="platform",
            name=PACKAGE_NAME,
            version=version,
            registry_url=wheel_publish_url,
        )

    print()
    print("=== Done ===")
    print(f"  Image:   {image_ref}:{version}")
    print(f"  API:     {api_url}/api/v1/compute-artifacts")


if __name__ == "__main__":
    main()
