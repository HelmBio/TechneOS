#!/usr/bin/env bash
# Shared image catalog for the EC2 deploy — the one place that maps each
# platform image to the package whose version tags it. Sourced by
# build-and-push.sh (to build + tag) and deploy.sh (to pin <SERVICE>_IMAGE_TAG on
# the host), so the two can never disagree on image names or versions.
#
# Each row is: name|manifest|dockerfile|context|revision-paths
#   name            image repo under techneos/ AND the compose service key
#   manifest        file whose `version` becomes the image tag (pyproject/package.json)
#   dockerfile      build file
#   context         build context
#   revision-paths  git paths whose last commit is the per-service "revision",
#                   used for the immutable {version}-{rev} tag and the no-bump
#                   warning. A pragmatic set (the package + shared core); the
#                   version bump — not this — is the real release control.
PLATFORM_IMAGES=(
  "gateway|packages/gateway/pyproject.toml|packages/gateway/Dockerfile|.|packages/gateway packages/core migrations"
  "auth-service|packages/services/auth/pyproject.toml|packages/services/auth/Dockerfile|.|packages/services/auth packages/core"
  "dataset-service|packages/services/dataset/pyproject.toml|packages/services/dataset/Dockerfile|.|packages/services/dataset packages/core"
  "tool-service|packages/services/tool/pyproject.toml|packages/services/tool/Dockerfile|.|packages/services/tool packages/core"
  "task-service|packages/services/task/pyproject.toml|packages/services/task/Dockerfile|.|packages/services/task packages/core"
  "pipeline-service|packages/services/pipeline/pyproject.toml|packages/services/pipeline/Dockerfile|.|packages/services/pipeline packages/core"
  "agent-service|packages/services/agent/pyproject.toml|packages/services/agent/Dockerfile|.|packages/services/agent packages/core"
  "app-service|packages/services/app/pyproject.toml|packages/services/app/Dockerfile|.|packages/services/app packages/core"
  "notification-service|packages/services/notification/pyproject.toml|packages/services/notification/Dockerfile|.|packages/services/notification packages/core"
  "portal|packages/portal/package.json|packages/portal/Dockerfile|packages/portal|packages/portal"
  "tool-runtime|packages/tool-runtime/pyproject.toml|packages/tool-runtime/Dockerfile|packages/tool-runtime|packages/tool-runtime"
)

# Version string from a package manifest ([project] version in pyproject.toml,
# or "version" in package.json).
pkg_version() {
  case "$1" in
    *.toml) grep -m1 -E '^version[[:space:]]*=' "$1" | sed -E 's/.*"([^"]+)".*/\1/' ;;
    *.json) grep -m1 '"version"' "$1" | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' ;;
  esac
}

# Short sha of the last commit touching a service's revision-paths — its
# per-service "revision". $1 is the space-separated path list, split into
# separate path args here (bash word-splitting). Empty outside a git checkout.
# NB: relies on bash word-splitting of unquoted $1 — run this under bash, not zsh.
service_revision() {
  local IFS=$' \t\n'
  # shellcheck disable=SC2086  # intentional split of the space-separated paths
  git log -1 --format=%h -- $1 2>/dev/null || true
}

# The compose/env override variable for an image:
#   auth-service -> AUTH_SERVICE_IMAGE_TAG,  gateway -> GATEWAY_IMAGE_TAG
image_tag_var() {
  printf '%s_IMAGE_TAG' "$(printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_')"
}

# True if the working tree has uncommitted changes under the given paths (or
# anywhere, when called with none). Tags come from committed history, so a dirty
# tree means the built revision won't reflect local edits.
worktree_dirty() {
  [ -n "$(git status --porcelain -- "$@" 2>/dev/null)" ]
}
