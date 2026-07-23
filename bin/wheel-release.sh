#!/usr/bin/env bash
set -euo pipefail
# wheel-release.sh — release Python package wheels (build → publish → register).
#
#   bin/wheel-release.sh <package> [--env local|prod] [--skip-build] [--skip-register] [--force]
#   bin/wheel-release.sh <package> --reset
#
# Packages:
#   cli            techneos-cli wheel (published to index)
#   management     techneos-management wheel (catalog registration scripts)
#   tool-runtime   techneos-tool-runtime wheel (container tools base image)
#   platform       all platform wheels (management + tool-runtime + cli)
#
# Default: build + publish + register. Use --skip-build to publish an existing
# wheel, or --skip-register to build and publish without recording in inventory.
#
# Version handling:
#   - If version exists in index and --force: overwrites the existing version
#   - If version exists in index and no --force: auto-bumps to {version}-{git}
#     with a warning to bump the version in pyproject.toml
#
# Examples:
#   bin/wheel-release.sh cli                              # full release
#   bin/wheel-release.sh platform --env=prod             # release to CodeArtifact
#   bin/wheel-release.sh management --skip-build         # publish only
#   bin/wheel-release.sh management --force              # overwrite existing version
#   bin/wheel-release.sh platform --reset                # clear all platform wheels + records

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── args ─────────────────────────────────────────────────────────────────────
show_help() {
  cat <<'EOF'
Usage: bin/wheel-release.sh <package> [options]
       bin/wheel-release.sh <package> --reset [options]

Release Python package wheels (build → publish → register).

Packages:
  cli            techneos-cli wheel (published to index)
  management     techneos-management wheel (catalog registration scripts)
  tool-runtime   techneos-tool-runtime wheel (container tools base image)
  platform       all platform wheels (management + tool-runtime + cli)

Options:
  --env <local|prod>    Target environment (default: local)
  --skip-build          Skip build step, publish existing wheel
  --skip-register       Skip inventory registration
  --force               Overwrite existing version in index (default: auto-bump)
  --reset               Clear wheels from index and delete compute_artifacts
  --upsert              Upsert existing artifact instead of creating new
  --help, -h            Show this help message

Version handling:
  If a version already exists in the index:
  - Without --force: auto-bumps to {version}-{git_sha} with a warning
  - With --force: overwrites the existing version

Examples:
  bin/wheel-release.sh cli                              # build CLI wheel
  bin/wheel-release.sh platform --env=prod             # release all to CodeArtifact
  bin/wheel-release.sh management --skip-build         # publish only
  bin/wheel-release.sh management --force              # overwrite existing version
  bin/wheel-release.sh tool-runtime --skip-register    # build + publish, no record
  bin/wheel-release.sh platform --reset                # clear all platform wheels + records
  bin/wheel-release.sh cli --reset                     # clear cli wheel + records

Notes:
  - All packages are published to the package index
  - Platform release builds all three packages (management, tool-runtime, cli)
EOF
  exit 0
}

# Check for --help/-h before positional arg
for arg in "$@"; do
  [ "$arg" = "--help" ] || [ "$arg" = "-h" ] && show_help
done

ENV_TARGET="local"; SKIP_BUILD="no"; SKIP_REGISTER="no"; FORCE="no"; RESET="no"; EXTRA_ARGS=()

# Parse flags first, then extract the positional package argument
while [ $# -gt 0 ]; do
  case "$1" in
    --env=*)          ENV_TARGET="${1#*=}"; shift ;;
    --env)            ENV_TARGET="$2"; shift 2 ;;
    --skip-build)     SKIP_BUILD="yes"; shift ;;
    --skip-register)  SKIP_REGISTER="yes"; shift ;;
    --force)          FORCE="yes"; shift ;;
    --reset)          RESET="yes"; shift ;;
    --upsert)         EXTRA_ARGS+=("--upsert"); shift ;;
    -*)               echo "Error: unknown flag '$1'" >&2; exit 2 ;;
    *)                PACKAGE="$1"; shift ;;
  esac
done

# --reset requires a package argument
if [ "$RESET" = "yes" ] && [ -z "${PACKAGE:-}" ]; then
  echo "Error: --reset requires a package argument (cli, management, tool-runtime, platform)" >&2
  exit 2
fi

if [ "$RESET" != "yes" ] && [ -z "${PACKAGE:-}" ]; then
  show_help
fi

case "$ENV_TARGET" in
  local|dev) ENV_TARGET="local" ;;
  prod|production) ENV_TARGET="prod" ;;
  *) echo "Error: --env must be local or prod" >&2; exit 2 ;;
esac

# ── package lookup ───────────────────────────────────────────────────────────
resolve_package() {
  local pkg="$1"
  case "$pkg" in
    cli)
      PKG_DIR="packages/cli"
      PKG_NAME="techneos-cli"
      ;;
    management)
      PKG_DIR="packages/management"
      PKG_NAME="techneos-management"
      ;;
    tool-runtime)
      PKG_DIR="packages/tool-runtime"
      PKG_NAME="techneos-tool-runtime"
      ;;
    platform)
      PKG_DIR=""
      PKG_NAME="platform"
      ;;
    *)
      echo "Error: unknown package '$pkg'" >&2
      echo "Known packages: cli, management, tool-runtime, platform" >&2
      exit 2
      ;;
  esac
}

# ── build ────────────────────────────────────────────────────────────────────
build_standard() {
  local pkg_dir="$1" out_dir="${2:-}"
  [ -n "$out_dir" ] && mkdir -p "$out_dir"
  if [ -n "$out_dir" ]; then
    uv build "$pkg_dir" --wheel -o "$out_dir"
  else
    uv build "$pkg_dir" --wheel
  fi
  echo "Built $PKG_NAME -> ${out_dir:-$pkg_dir/dist/}"
}

do_build() {
  echo "=== Building $PKG_NAME ==="
  case "$PKG_NAME" in
    techneos-cli|techneos-management|techneos-tool-runtime)
      build_standard "$PKG_DIR"
      ;;
    platform)
      echo "--- techneos-tool-runtime ---"
      build_standard "packages/tool-runtime"
      echo
      echo "--- techneos-management ---"
      build_standard "packages/management"
      echo
      echo "--- techneos-cli ---"
      build_standard "packages/cli"
      ;;
  esac
}

# ── publish + register ───────────────────────────────────────────────────────
# Load an env file into the environment WITHOUT sourcing it. The prod env file
# holds values with spaces and shell metacharacters (e.g. PLATFORM_SITE_TAGLINE),
# which `source` would try to execute — that is why the deploy scripts read it
# via grep rather than sourcing. Assign each KEY=VALUE literally so the child
# `uv run python` publishers inherit exactly the intended values.
_load_env_file() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac      # skip blanks + comments
    key="${line%%=*}"
    [ "$key" = "$line" ] && continue               # no '=' → not an assignment
    case "$key" in "export "*) key="${key#export }" ;; esac
    case "$key" in *[!A-Za-z0-9_]*) continue ;; esac  # not a valid shell name
    val="${line#*=}"
    # Strip one layer of matching surrounding quotes, mirroring `source`.
    case "$val" in
      \"*\") val="${val#\"}"; val="${val%\"}" ;;
      \'*\') val="${val#\'}"; val="${val%\'}" ;;
    esac
    export "$key=$val"
  done < "$file"
}

validate_env() {
  # Check required env vars after loading the env file. A <placeholder> counts
  # as unset. Exits with a clear message listing all missing vars at once.
  local env_file="${1:-}"
  _missing=()

  # Required for all publishes: at least one of index URL or publish URL
  local have_index="${PYTHON_PACKAGE_INDEX_URL:-}"
  local have_publish="${PYTHON_PACKAGE_PUBLISH_URL:-}"
  if [ -z "$have_index" ] && [ -z "$have_publish" ]; then
    _missing+=("PYTHON_PACKAGE_INDEX_URL (or PYTHON_PACKAGE_PUBLISH_URL)")
  else
    # Check for <placeholder> values
    [[ "$have_index" == *"<"* ]] && _missing+=("PYTHON_PACKAGE_INDEX_URL — still has <placeholder>")
    [[ "$have_publish" == *"<"* ]] && _missing+=("PYTHON_PACKAGE_PUBLISH_URL — still has <placeholder>")
  fi

  # Registration requires the gateway URL
  if [ "$SKIP_REGISTER" != "yes" ]; then
    case "${PLATFORM_API_URL:-}" in
      "") _missing+=("PLATFORM_API_URL") ;;
      *"<"*) _missing+=("PLATFORM_API_URL — still has <placeholder>") ;;
    esac
  fi

  if [ "${#_missing[@]}" -gt 0 ]; then
    echo "ERROR: required environment variables are unset or still <placeholders>" >&2
    if [ -n "$env_file" ]; then
      echo "       in $env_file (or the environment):" >&2
    else
      echo "       in the environment:" >&2
    fi
    printf '         - %s\n' "${_missing[@]}" >&2
    echo "       Fill them in, then re-run." >&2
    exit 1
  fi
}

do_release() {
  local extra_args=()
  [ ${#EXTRA_ARGS[@]} -gt 0 ] && extra_args=("${EXTRA_ARGS[@]}")
  [ "$SKIP_REGISTER" = "yes" ] && extra_args+=("--skip-register")
  [ "$FORCE" = "yes" ] && extra_args+=("--force")
  # Forward the target env to the publish scripts. They each load their own env
  # file with override=True (defaulting to local), so without this the child
  # would reload .env over the prod vars we exported and publish to localhost.
  extra_args+=("--env" "$ENV_TARGET")

  # Load env file for publish credentials
  local env_file=""
  case "$ENV_TARGET" in
    local) env_file="$REPO_ROOT/.env"; [ -f "$env_file" ] && _load_env_file "$env_file" ;;
    prod)  env_file="$REPO_ROOT/deploy/ec2/.env.prod"; [ -f "$env_file" ] && _load_env_file "$env_file" ;;
  esac

  validate_env "$env_file"

  if [ "$PKG_NAME" = "platform" ]; then
    echo "=== Releasing techneos-tool-runtime ==="
    uv run python setup/wheels/publish_tool_runtime.py \
      --skip-build --skip-push --publish-wheel ${extra_args[@]+"${extra_args[@]}"}
    echo
    echo "=== Releasing techneos-management ==="
    uv run python setup/wheels/publish_management.py ${extra_args[@]+"${extra_args[@]}"}
    echo
    echo "=== Releasing techneos-cli ==="
    uv run python setup/wheels/publish_cli.py ${extra_args[@]+"${extra_args[@]}"}
    echo
    echo "=== All platform wheels released ==="
  elif [ "$PKG_NAME" = "techneos-cli" ]; then
    echo "=== Releasing $PKG_NAME ==="
    uv run python setup/wheels/publish_cli.py ${extra_args[@]+"${extra_args[@]}"}
  else
    local script="$REPO_ROOT/setup/wheels/publish_${PKG_DIR##*/}.py"
    if [ -f "$script" ]; then
      echo "=== Releasing $PKG_NAME ==="
      uv run python "$script" ${extra_args[@]+"${extra_args[@]}"}
    else
      echo "Error: no publish script found at $script" >&2
      exit 1
    fi
  fi
}

# ── reset ────────────────────────────────────────────────────────────────────
do_reset() {
  # Clear wheels from the package index and compute_artifact records.
  # Usage: do_reset <package>
  local pkg="${1:-platform}"

  # Load env file
  local env_file=""
  case "$ENV_TARGET" in
    local) env_file="$REPO_ROOT/.env"; [ -f "$env_file" ] && _load_env_file "$env_file" ;;
    prod)  env_file="$REPO_ROOT/deploy/ec2/.env.prod"; [ -f "$env_file" ] && _load_env_file "$env_file" ;;
  esac

  validate_env "$env_file"

  # Authenticate upfront — need token for compute_artifacts query
  echo "=== Authenticating ==="
  local api_url="${PLATFORM_API_URL:-}"
  if [ -z "$api_url" ]; then
    echo "Error: PLATFORM_API_URL not set." >&2
    exit 2
  fi

  local token_file
  token_file=$(mktemp)
  trap "rm -f '$token_file'" EXIT

  uv run python -c "
from management.auth import authenticate
info = authenticate('$api_url', env_name='$ENV_TARGET')
with open('$token_file', 'w') as f:
    f.write(info.token)
" || {
    echo "Error: Authentication failed." >&2
    exit 1
  }

  local token
  token=$(cat "$token_file")
  rm -f "$token_file"
  trap - EXIT

  if [ -z "$token" ] || [[ "$token" != eyJ* ]]; then
    echo "Error: Failed to obtain valid token." >&2
    exit 1
  fi

  # Determine which packages to reset
  local packages=()
  case "$pkg" in
    platform)   packages=(cli management tool-runtime) ;;
    cli)        packages=(cli) ;;
    management) packages=(management) ;;
    tool-runtime) packages=(tool-runtime) ;;
    *)          echo "Error: unknown package '$pkg'" >&2; exit 2 ;;
  esac

  # Dry-run: show what will be affected
  echo
  echo "=== Dry-run: ${pkg} reset ==="
  echo

  # Show wheels in index
  echo "Wheels in package index:"
  local index_url="${PYTHON_PACKAGE_INDEX_URL:-}"
  local publish_url="${PYTHON_PACKAGE_PUBLISH_URL:-}"
  local has_wheels=false

  if [[ "$publish_url" == *"localhost"* ]] || [[ "$publish_url" == *"devpi"* ]]; then
    local container=$(docker ps --filter "ancestor=pypiserver/pypiserver" --format "{{.Names}}" 2>/dev/null | head -1)
    if [ -n "$container" ]; then
      for p in "${packages[@]}"; do
        resolve_package "$p"
        local underscore_name="${PKG_NAME//-/_}"
        local files=$(docker exec "$container" ls /data/packages/ 2>/dev/null \
          | grep -E "^(${PKG_NAME}|${underscore_name})-" || true)
        if [ -n "$files" ]; then
          has_wheels=true
          echo "$files" | while read -r f; do
            echo "  - $f"
          done
        fi
      done
    fi
  fi

  if [ "$has_wheels" = false ]; then
    echo "  (none found)"
  fi

  # Show compute_artifacts
  echo
  echo "Compute artifacts to delete:"
  local has_artifacts=false

  for p in "${packages[@]}"; do
    resolve_package "$p"
    # Query by wheel name (techneos-tool-runtime) and Docker image name (techneos/tool-runtime)
    local docker_name="techneos/${p}"
    local artifacts=$(curl -s -H "Authorization: Bearer $token" \
      "${api_url}/api/v1/compute-artifacts?origin=platform&name=${PKG_NAME}" 2>/dev/null)
    local docker_artifacts=$(curl -s -H "Authorization: Bearer $token" \
      "${api_url}/api/v1/compute-artifacts?origin=platform&name=${docker_name}" 2>/dev/null)

    # Merge results (deduplicate by id)
    local all_artifacts=$(printf '%s\n%s\n' "$artifacts" "$docker_artifacts" | uv run python -c "
import sys, json
seen = set()
result = []
for line in sys.stdin:
    try:
        items = json.loads(line.strip())
        if isinstance(items, list):
            for a in items:
                aid = a.get('id')
                if aid and aid not in seen:
                    seen.add(aid)
                    result.append(a)
    except:
        pass
print(json.dumps(result))
" 2>/dev/null)

    if [ -n "$all_artifacts" ] && [ "$all_artifacts" != "[]" ]; then
      has_artifacts=true
      echo "$all_artifacts" | uv run python -c "
import sys, json
artifacts = json.load(sys.stdin)
for a in artifacts:
    print(f\"  - {a.get('name', '?')}:{a.get('version', '?')} ({a.get('kind', '?')})\")
" 2>/dev/null
    fi
  done

  if [ "$has_artifacts" = false ]; then
    echo "  (none found)"
  fi

  # Exit early if nothing to delete
  if [ "$has_wheels" = false ] && [ "$has_artifacts" = false ]; then
    echo
    echo "Nothing to delete."
    exit 0
  fi

  # Confirm
  echo
  read -p "Proceed with deletion? (yes/no): " confirm
  if [ "$confirm" != "yes" ]; then
    echo "Aborted."
    exit 0
  fi

  # Execute
  echo
  echo "=== Clearing wheels from package index ==="
  for p in "${packages[@]}"; do
    resolve_package "$p"
    echo "  Clearing ${PKG_NAME}..."
    _clear_index_for_package "$p"
  done

  echo
  echo "=== Deleting compute_artifacts ==="
  # Collect docker images to remove before deleting records
  local docker_images=()
  for p in "${packages[@]}"; do
    resolve_package "$p"
    local docker_name="techneos/${p}"
    # Query both wheel and Docker image names
    local artifacts=$(curl -s -H "Authorization: Bearer $token" \
      "${api_url}/api/v1/compute-artifacts?origin=platform&name=${PKG_NAME}" 2>/dev/null)
    local docker_artifacts=$(curl -s -H "Authorization: Bearer $token" \
      "${api_url}/api/v1/compute-artifacts?origin=platform&name=${docker_name}" 2>/dev/null)

    # Collect Docker images from both queries
    for art in "$artifacts" "$docker_artifacts"; do
      if [ -n "$art" ] && [ "$art" != "[]" ]; then
        while IFS= read -r img; do
          if [ -n "$img" ]; then
            docker_images+=("$img")
          fi
        done < <(echo "$art" | uv run python -c "
import sys, json
for a in json.load(sys.stdin):
    if a.get('kind') == 'docker_image':
        print(a.get('name', ''))
" 2>/dev/null)
      fi
    done

    # Delete artifacts by name (wheel format)
    _clear_compute_artifacts "$PKG_NAME" "$token" "$api_url"
    # Also delete Docker image artifacts
    _clear_compute_artifacts "$docker_name" "$token" "$api_url"
  done

  # Remove Docker images
  if [ ${#docker_images[@]} -gt 0 ]; then
    echo
    echo "=== Removing Docker images ==="
    for img in "${docker_images[@]}"; do
      if [ -n "$img" ]; then
        echo "  Removing ${img}..."
        docker rmi "$img:latest" 2>/dev/null || true
        docker rmi "$img" 2>/dev/null || true
      fi
    done
  fi

  echo
  echo "=== Reset complete ==="
}

_clear_index_for_package() {
  # Delete wheels for a specific package from the package index.
  # Usage: _clear_index_for_package <package>  (cli, management, tool-runtime)
  local pkg="$1"
  local pkg_name
  case "$pkg" in
    cli)          pkg_name="techneos-cli" ;;
    management)   pkg_name="techneos-management" ;;
    tool-runtime) pkg_name="techneos-tool-runtime" ;;
    *)            echo "  Unknown package: $pkg"; return ;;
  esac

  local index_url="${PYTHON_PACKAGE_INDEX_URL:-}"
  local publish_url="${PYTHON_PACKAGE_PUBLISH_URL:-}"

  if [ -z "$index_url" ] && [ -z "$publish_url" ]; then
    echo "  No package index configured, skipping."
    return
  fi

  if [[ "$publish_url" == *"localhost"* ]] || [[ "$publish_url" == *"devpi"* ]]; then
    _clear_devpi_package "$pkg_name"
  elif [[ "$publish_url" == *"codeartifact"* ]] || [[ "$index_url" == *"codeartifact"* ]]; then
    _clear_codeartifact_package "$pkg_name"
  else
    echo "  Unknown index type, skipping."
  fi
}

_clear_devpi_package() {
  local pkg_name="$1"  # e.g. techneos-management
  local container=$(docker ps --filter "ancestor=pypiserver/pypiserver" --format "{{.Names}}" 2>/dev/null | head -1)

  if [ -z "$container" ]; then
    echo "  pypiserver container not found. Skipping."
    return
  fi

  # Find matching wheels (underscore variant of the package name)
  local underscore_name="${pkg_name//-/_}"
  local files=$(docker exec "$container" ls /data/packages/ 2>/dev/null \
    | grep -E "^(${pkg_name}|${underscore_name})-" || true)

  if [ -z "$files" ]; then
    echo "  No ${pkg_name} wheels in index."
    return
  fi

  echo "$files" | while read -r f; do
    echo "  Deleting $f ..."
    docker exec "$container" rm "/data/packages/$f" 2>/dev/null || true
  done
}

_clear_codeartifact_package() {
  local pkg_name="$1"
  if ! command -v aws &> /dev/null; then
    echo "  AWS CLI not found. Skipping CodeArtifact clear."
    return
  fi

  local domain="${CODEARTIFACT_DOMAIN:-}"
  local owner="${CODEARTIFACT_DOMAIN_OWNER:-}"
  local repo="${CODEARTIFACT_REPOSITORY:-}"

  if [ -z "$domain" ] || [ -z "$owner" ] || [ -z "$repo" ]; then
    echo "  CodeArtifact coordinates not set. Skipping."
    return
  fi

  aws codeartifact delete-package \
    --domain "$domain" --domain-owner "$owner" --repository "$repo" \
    --package "$pkg_name" 2>/dev/null || true
}

_clear_compute_artifacts() {
  # Delete compute_artifact records via gateway proxy.
  # Usage: _clear_compute_artifacts <name_filter> <token> <api_url>
  local name_filter="$1"
  local token="$2"
  local api_url="$3"

  # Build query params
  local query="origin=platform"
  if [ -n "$name_filter" ]; then
    query="${query}&name=${name_filter}"
  fi

  # List matching artifacts
  echo "  Listing compute_artifacts (${query})..."
  local artifacts=$(curl -s -H "Authorization: Bearer $token" \
    "${api_url}/api/v1/compute-artifacts?${query}" 2>/dev/null)

  if [ -z "$artifacts" ] || [ "$artifacts" = "[]" ]; then
    echo "  No matching compute_artifacts found."
    return
  fi

  # Delete each artifact by ID
  echo "$artifacts" | uv run python -c "
import sys, json
import httpx

artifacts = json.load(sys.stdin)
token = '$token'
api_url = '$api_url'

for a in artifacts:
    aid = a.get('id')
    if not aid:
        continue
    name = a.get('name', '?')
    ver = a.get('version', '?')
    print(f'  Deleting {name}:{ver}...')
    r = httpx.delete(
        f'{api_url}/api/v1/compute-artifacts/{aid}',
        headers={'Authorization': f'Bearer {token}'},
    )
    status = 'OK' if r.status_code in (200, 204) else f'Failed ({r.status_code})'
    print(f'    {status}')
" 2>/dev/null
}

# ── main ─────────────────────────────────────────────────────────────────────
if [ "$RESET" = "yes" ]; then
  do_reset "${PACKAGE:-platform}"
  exit 0
fi

resolve_package "$PACKAGE"

if [ "$SKIP_BUILD" != "yes" ]; then
  do_build
  echo
fi

do_release
