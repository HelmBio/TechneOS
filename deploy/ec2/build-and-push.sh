#!/usr/bin/env bash
set -euo pipefail

# Build the platform's 11 images and push them to the registry the EC2
# deployment pulls from.
#
# WHERE THIS RUNS: your workstation or a release host with Docker + registry
# credentials — NOT the target instance. The instance only pulls.
#
# CRITICAL — architecture: builds for linux/amd64 via buildx. The target is an
# x86 EC2 instance; a native build on an arm64 Mac produces images that fail to
# start there with an opaque exec-format error. This is not optional.
#
# The portal is baked per-deployment: NEXT_PUBLIC_* is inlined into the client
# bundle at build time from --build-arg, so the image is specific to one
# PLATFORM_API_URL. A runtime env var cannot change it.
#
#   Usage:  deploy/ec2/build-and-push.sh
#           (reads deploy/ec2/.env.prod for IMAGE_REGISTRY, PLATFORM_API_URL,
#            ...; each image is tagged with its own package version)

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
cd "$REPO_ROOT"

# The image catalog (name -> manifest/dockerfile/context/revision-paths) and the
# version/revision helpers, shared with deploy.sh so tags can't drift.
source "$HERE/_image-catalog.sh"

# Read only the (non-secret) build vars, LITERALLY — not by sourcing. The env
# file holds ${VAR} placeholders and secret values; `source` would treat `<`,
# spaces, `$` etc. as shell syntax. An unfilled <placeholder> counts as unset
# (the guards below then fire). Image tags come from each package's version, not
# from this file.
ENV_FILE="${ENV_FILE:-$HERE/.env.prod}"
_envval() {
  local v
  [ -f "$ENV_FILE" ] || return 0
  v="$(grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)"
  case "$v" in *"<"*) return 0 ;; esac
  printf '%s' "$v"
}

IMAGE_REGISTRY="${IMAGE_REGISTRY:-$(_envval IMAGE_REGISTRY)}"
AWS_REGION="${AWS_REGION:-$(_envval AWS_REGION)}"
PLATFORM_API_URL="${PLATFORM_API_URL:-$(_envval PLATFORM_API_URL)}"
PLATFORM_SITE_NAME="${PLATFORM_SITE_NAME:-$(_envval PLATFORM_SITE_NAME)}"
PLATFORM_SITE_TAGLINE="${PLATFORM_SITE_TAGLINE:-$(_envval PLATFORM_SITE_TAGLINE)}"

# Fail fast, together, on what the build can't proceed without. A <placeholder>
# counts as unset. IMAGE_REGISTRY is the push target; PLATFORM_API_URL is inlined
# into the portal bundle at build time, so it must be real. There is no global
# IMAGE_TAG — each image is tagged with its own package version.
_missing=()
case "${IMAGE_REGISTRY:-}"   in ""|*"<"*) _missing+=("IMAGE_REGISTRY") ;; esac
case "${PLATFORM_API_URL:-}" in ""|*"<"*) _missing+=("PLATFORM_API_URL") ;; esac
if [ "${#_missing[@]}" -gt 0 ]; then
  echo "ERROR: required build variables are unset or still <placeholders>" >&2
  echo "       in $ENV_FILE (or the environment):" >&2
  printf '         - %s\n' "${_missing[@]}" >&2
  echo "       Fill them in — see $HERE/.env.prod.example — then re-run." >&2
  exit 1
fi

# AWS_REGION is used only for the ECR login, and the ECR hostname already names
# the region (<account>.dkr.ecr.<region>.amazonaws.com) — authoritative, since a
# token minted for another region won't authenticate here — so derive it. For
# non-ECR registries fall back to the env value, then us-east-1.
if [[ "$IMAGE_REGISTRY" == *.dkr.ecr.*.amazonaws.com* ]]; then
  AWS_REGION="$(printf '%s' "$IMAGE_REGISTRY" | sed -E 's#.*\.dkr\.ecr\.([^.]+)\.amazonaws\.com.*#\1#')"
fi
AWS_REGION="${AWS_REGION:-us-east-1}"

echo "=== Registry: $IMAGE_REGISTRY ==="

# Registry login. ECR needs a minted token; anything else (GHCR, …) is assumed
# already logged in — the one ECR-specific step, gated so a registry switch
# needs no change here beyond a prior `docker login`.
if [[ "$IMAGE_REGISTRY" == *.dkr.ecr.*.amazonaws.com* ]]; then
  echo "=== Logging into ECR ==="
  aws ecr get-login-password --region "$AWS_REGION" \
    | docker login --username AWS --password-stdin "$IMAGE_REGISTRY"
else
  echo "=== Non-ECR registry — assuming 'docker login $IMAGE_REGISTRY' already done ==="
fi

# Tags come from committed history — warn if the tree is dirty, since local edits
# won't be reflected in the {version}-{rev} tag.
if worktree_dirty; then
  echo "WARNING: the working tree has uncommitted changes. Image revisions come"
  echo "         from git history, so those edits are NOT in the {version}-{rev}"
  echo "         tags. Commit them for an accurate build."
fi

# True if a tag already exists in the registry (needs the login above).
tag_exists() { docker buildx imagetools inspect "$1" >/dev/null 2>&1; }

# Build + push one image, tagged with its package version, for linux/amd64
# (the target is x86; a native arm64 build would fail to start there). A per-repo
# layer cache in the registry keeps unchanged layers from rebuilding. Each build
# also gets an immutable {version}-{rev} tag (rev = last commit touching the
# service). The plain {version} — what deploy pins — is only published on the
# FIRST build of that version: once it exists, a changed-but-not-bumped build
# publishes {version}-{rev} only and leaves {version} alone, so a live deploy
# never silently changes under it.
build_one() {
  local name=$1 manifest=$2 dockerfile=$3 context=$4 revpaths=$5
  local version rev target
  version="$(pkg_version "$manifest")"
  rev="$(service_revision "$revpaths")"
  [ -n "$version" ] || { echo "ERROR: no version found in $manifest" >&2; exit 1; }
  [ -n "$rev" ]     || { echo "ERROR: cannot compute a git revision for $name (not a checkout?)" >&2; exit 1; }
  target="$IMAGE_REGISTRY/techneos/$name"

  if tag_exists "$target:$version-$rev"; then
    echo "=== $name: $version-$rev already published — skipping ==="
    return
  fi

  local args=(
    docker buildx build
    --platform linux/amd64
    --cache-from "type=registry,ref=$target:buildcache"
    --cache-to   "type=registry,ref=$target:buildcache,mode=max,image-manifest=true,oci-mediatypes=true"
    -f "$dockerfile"
    -t "$target:$version-$rev"
  )
  if tag_exists "$target:$version"; then
    echo "WARNING: $name $version is already published, from different code."
    echo "         Publishing $version-$rev only; the deployable $name:$version is"
    echo "         unchanged. Bump 'version' in $manifest to release these changes."
  else
    echo "=== $name: first build of $version (also tagged $version-$rev) ==="
    args+=(-t "$target:$version")
  fi
  # The portal is the only image with build-time args (branding + API URL baked
  # into the client bundle).
  if [ "$name" = "portal" ]; then
    args+=(
      --build-arg "PLATFORM_API_URL=$PLATFORM_API_URL"
      --build-arg "PLATFORM_SITE_NAME=${PLATFORM_SITE_NAME:-TechneOS}"
      --build-arg "PLATFORM_SITE_TAGLINE=${PLATFORM_SITE_TAGLINE:-}"
    )
  fi
  args+=(--push "$context")
  "${args[@]}"
}

for _row in "${PLATFORM_IMAGES[@]}"; do
  IFS='|' read -r _name _manifest _dockerfile _context _revpaths <<<"$_row"
  build_one "$_name" "$_manifest" "$_dockerfile" "$_context" "$_revpaths"
done

echo "=== Build complete → $IMAGE_REGISTRY ==="
