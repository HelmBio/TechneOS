#!/usr/bin/env bash
set -euo pipefail

# Build the techneos-cli wheel the gateway serves at /cli/simple/, stamped with
# the commit it was built from: 0.1.0+g1a2b3c4, or +g1a2b3c4.dirty with
# uncommitted changes in the package.
#
# WHY STAMP: pip and uv key their caches on name + version. A rebuild that keeps
# the same version is invisible to them — they report success and install the
# copy they already had, so a change appears not to have taken effect. Every
# build getting its own version removes that failure entirely.
#
# The stamp is for development. Release wheels are built by the gateway image
# (packages/gateway/Dockerfile) straight from pyproject.toml, so what customers
# install carries the plain version — a distinct one per release, which is why
# the caches behave for them.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

PKG_DIR="packages/cli"
OUT_DIR="cli-dist"

base_version="$(perl -ne 'print $1 and last if /^version = "([^"]+)"/' "$PKG_DIR/pyproject.toml")"
if [[ -z "$base_version" ]]; then
  echo "Could not read version from $PKG_DIR/pyproject.toml" >&2
  exit 1
fi

# Digest of everything that goes into the wheel. A bare ".dirty" marker would be
# the same string on every rebuild, leaving the caches serving a stale wheel for
# exactly the loop this stamp exists for: editing without committing. Keying on
# content instead means a version changes when — and only when — the code does.
content_digest() {
  find "$PKG_DIR/src" "$PKG_DIR/pyproject.toml" -type f -not -name '*.pyc' -not -path '*/__pycache__/*' \
    | LC_ALL=C sort \
    | xargs shasum -a 256 2>/dev/null \
    | shasum -a 256 \
    | cut -c1-8
}

version="$base_version"
if git rev-parse --git-dir >/dev/null 2>&1; then
  sha="$(git rev-parse --short HEAD 2>/dev/null || echo "")"
  if [[ -n "$sha" ]]; then
    version="${base_version}+g${sha}"
    # Only the package's own files reach the wheel, so only they can dirty it.
    if [[ -n "$(git status --porcelain "$PKG_DIR")" ]]; then
      version="${version}.d$(content_digest)"
    fi
  fi
fi

# Build from a copy: the version has to be rewritten to reach hatchling, and a
# build that fails partway must not leave a mangled pyproject.toml behind.
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
cp -R "$PKG_DIR" "$staging/cli"
perl -pi -e "s/^version = \"\Q$base_version\E\"/version = \"$version\"/" "$staging/cli/pyproject.toml"

rm -rf "$OUT_DIR"
uv build "$staging/cli" --wheel -o "$OUT_DIR"

echo
echo "Built techneos-cli $version -> $OUT_DIR/"
echo "The gateway serves it at /cli/simple/ (no restart needed)."
