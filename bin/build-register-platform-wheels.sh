#!/usr/bin/env bash
set -euo pipefail

# Build and publish the platform wheels that CATALOG packages depend on to the
# Python package index (DevPI locally, CodeArtifact in prod), so a standalone
# catalog repo can resolve them by version. Each wheel is also registered in the
# compute_artifacts inventory (origin=platform).
#
# WHERE THIS RUNS: a workstation or CI runner that has the package SOURCE and
# publish credentials. It is intentionally NOT part of the EC2 deploy: that host
# only has the deploy bundle, not the packages/ source. This mirrors how catalog
# wheels are published — manually, per release.
#
# Wheels published here:
#   techneos-tool-runtime  (container tools build FROM it + import its helpers)
#   techneos-management    (catalog build/register scripts import it)
# NOT platform-assistant — it is platform-internal (ships inside the agent-service
# image), so it never goes to the index.
#
# Usage (args pass through to each build script):
#   bin/build-register-platform-wheels.sh                                # --env=local (DevPI)
#   bin/build-register-platform-wheels.sh  --env=prod                    # CodeArtifact
#   bin/build-register-platform-wheels.sh  --env=prod --skip-register    # publish only, don't record
#   bin/build-register-platform-wheels.sh  --env=prod --email a@b.c --password ...

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "=== REPO ROOT: $REPO_ROOT ==="
cd "$REPO_ROOT"

echo "=== Publishing techneos-tool-runtime wheel ==="
# tool-runtime's script is image-primary; --skip-build/--skip-push limit it to
# the wheel (the prod image is built by the deploy build step, not here).
uv run python setup/wheels/publish_tool_runtime.py \
  --skip-build --skip-push --publish-wheel "$@"
echo

echo "=== Publishing techneos-management wheel ==="
uv run python setup/wheels/publish_management.py "$@"
echo

echo "=== All platform wheels published ==="
