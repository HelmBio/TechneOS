#!/usr/bin/env python3
"""Ingest a build-artifacts manifest into the compute_artifacts inventory.

A gateway operation: it authenticates as a platform admin and POSTs each entry
to ``/api/v1/compute-artifacts`` — the same idempotent upsert the catalog build
scripts use. Run once the stack is up, alongside ``register_platform_assistant``.
Platform-service and tool-runtime images are built in the CodePipeline build
stage where the gateway isn't reachable; ``build-and-push.sh`` emits a manifest
that this script ingests afterwards.

The manifest is a JSON array of objects::

    [{"kind": "docker_image", "origin": "platform",
      "name": "techneos/gateway", "version": "abc123def456",
      "registry_url": "…dkr.ecr…", "digest": "sha256:…"}, …]

Read from a path argument or stdin::

    python setup/register_compute_artifacts.py build-artifacts.json
    python setup/register_compute_artifacts.py < manifest.json

Idempotent server-side on (kind, name, version, registry_url).
"""

import argparse
import json
import sys
from typing import Any

from management.registration import (
    add_auth_args,
    add_env_arg,
    auth_headers,
    authenticate,
    record_artifact,
    resolve_api_url,
)


def ingest(api_url: str, headers: dict[str, Any], manifest: list[dict[str, Any]]) -> None:
    for entry in manifest:
        record_artifact(
            api_url,
            headers,
            kind=entry["kind"],
            origin=entry.get("origin", "other"),
            name=entry["name"],
            version=entry["version"],
            registry_url=entry.get("registry_url"),
            digest=entry.get("digest"),
            source_commit_sha=entry.get("source_commit_sha"),
            metadata=entry.get("metadata"),
        )
    print(f"Artifact inventory: ingested {len(manifest)} entr{'y' if len(manifest) == 1 else 'ies'}.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest a build-artifacts manifest into the compute_artifacts inventory.",
    )
    add_env_arg(parser)
    add_auth_args(parser)
    parser.add_argument(
        "manifest",
        nargs="?",
        default=None,
        help="Path to the manifest JSON (reads stdin if omitted)",
    )
    args = parser.parse_args()

    if args.manifest:
        with open(args.manifest) as f:
            raw = f.read()
    else:
        raw = sys.stdin.read()
    raw = raw.strip()
    if not raw:
        print("No manifest content — nothing to ingest.")
        return
    manifest = json.loads(raw)
    if not isinstance(manifest, list):
        print("Error: manifest must be a JSON array.", file=sys.stderr)
        sys.exit(1)

    api_url = resolve_api_url(args.env)
    print(f"=== Target environment: {args.env} ===")
    print(f"  API URL:  {api_url}")
    print()

    token = authenticate(api_url, args.env, args.email, args.password)
    headers = auth_headers(token)
    ingest(api_url, headers, manifest)


if __name__ == "__main__":
    main()
