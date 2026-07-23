#!/usr/bin/env bash
set -euo pipefail

# Delete every image from ECR repositories in one region, leaving the now-empty
# repositories in place. By default clears ALL repos named "<prefix>*" (prefix
# defaults to "techneos/"); pass a REPO name to clear just that one — useful for
# republishing a single service's {version} tag after a code fix without bumping
# the version (e.g. clear techneos/gateway, then re-run build-and-push.sh).
#
# WHY keep the repos: `docker push` to ECR does not auto-create a repository, so
# deleting the repos would break the next build-and-push.sh. Emptying them is
# enough — with no tags left, build-and-push.sh takes its first-build path and
# republishes the plain {version} tags (see its header) instead of skipping them.
#
# WHERE THIS RUNS: your workstation, with AWS credentials that can manage ECR in
# the target account. It touches ONLY the registry, never the running instance.
#
#   Usage:
#     deploy/ec2/clear-ecr-images.sh [REPO] [--region R] [--prefix P] [--yes] [--dry-run]
#
#     REPO          Repository to clear, given without the prefix (e.g. "gateway"
#                   for techneos/gateway; the prefix is added if you omit it).
#                   Default: "all" — every repository under --prefix.
#     --region R    ECR region. Default: AWS_REGION env, else the region parsed
#                   from DOCKER_IMAGE_REGISTRY in deploy/ec2/.env.prod, else us-east-1.
#     --prefix P    Repository-name prefix to match, and prepended to REPO.
#                   Default: techneos/
#     --yes, -y     Skip the confirmation prompt (for non-interactive use).
#     --dry-run     List what would be deleted and exit without deleting.

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/.env.prod}"

usage() {
  cat <<'EOF'
Delete every image from ECR repositories in one region, keeping the now-empty
repositories in place. Clears all repos named "<prefix>*" (prefix defaults to
"techneos/"), or just one if a REPO name is given.

Usage:
  deploy/ec2/clear-ecr-images.sh [REPO] [--region R] [--prefix P] [--yes] [--dry-run]

  REPO          Repository to clear, given without the prefix (e.g. "gateway"
                for techneos/gateway; the prefix is added if you omit it).
                Default: "all" — every repository under --prefix.
  --region R    ECR region. Default: AWS_REGION env, else the region parsed
                from DOCKER_IMAGE_REGISTRY in deploy/ec2/.env.prod, else us-east-1.
  --prefix P    Repository-name prefix to match, and prepended to REPO. Default: techneos/
  --yes, -y     Skip the confirmation prompt (for non-interactive use).
  --dry-run     List what would be deleted and exit without deleting.
EOF
}

PREFIX="techneos/"
REGION="${AWS_REGION:-}"
REPO="all"
ASSUME_YES=0
DRY_RUN=0
_repo_set=0

while [ $# -gt 0 ]; do
  case "$1" in
    --region) REGION="$2"; shift 2 ;;
    --prefix) PREFIX="$2"; shift 2 ;;
    --yes|-y) ASSUME_YES=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "ERROR: unknown option: $1" >&2; usage >&2; exit 2 ;;
    *)
      [ "$_repo_set" -eq 0 ] || { echo "ERROR: unexpected extra argument: $1" >&2; usage >&2; exit 2; }
      REPO="$1"; _repo_set=1; shift ;;
  esac
done

# Read a var from .env.prod literally (never sourced — the file holds secrets and
# ${...} placeholders that `source` would mangle).
_envval() {
  [ -f "$ENV_FILE" ] || return 0
  grep -E "^$1=" "$ENV_FILE" 2>/dev/null | tail -1 | cut -d= -f2- || true
}

# Region: flag/env already in REGION; else derive from the ECR host in .env.prod;
# else us-east-1. The ECR hostname names its own region authoritatively.
if [ -z "$REGION" ]; then
  _reg="$(_envval DOCKER_IMAGE_REGISTRY)"
  if [[ "$_reg" == *.dkr.ecr.*.amazonaws.com* ]]; then
    REGION="$(printf '%s' "$_reg" | sed -E 's#.*\.dkr\.ecr\.([^.]+)\.amazonaws\.com.*#\1#')"
  fi
fi
REGION="${REGION:-us-east-1}"

# Resolve the name filter. "all" matches every repo under $PREFIX; a specific
# REPO matches exactly one — the $PREFIX is prepended unless you already included
# it, so both "gateway" and "techneos/gateway" name techneos/gateway.
if [ "$REPO" = "all" ]; then
  SCOPE="${PREFIX}*"
else
  case "$REPO" in
    "$PREFIX"*) TARGET="$REPO" ;;
    *)          TARGET="${PREFIX}${REPO}" ;;
  esac
  SCOPE="$TARGET"
fi

command -v aws >/dev/null 2>&1 || { echo "ERROR: aws CLI not found" >&2; exit 1; }

# Show which account/identity we're about to act on — a wrong-account delete is
# the main hazard here, so make it visible before anything is removed.
echo "=== Target ==="
echo "  Region:  $REGION"
echo "  Scope:   $SCOPE"
CALLER="$(aws sts get-caller-identity --query 'Arn' --output text 2>/dev/null || true)"
echo "  Caller:  ${CALLER:-<could not resolve — check credentials>}"
[ -n "$CALLER" ] || { echo "ERROR: no usable AWS credentials for this shell." >&2; exit 1; }

# Match the repository name(s) in the shell (a JMESPath literal can't take a
# shell variable cleanly): a prefix match for "all", an exact match otherwise.
_match() {
  if [ "$REPO" = "all" ]; then grep "^${PREFIX}"; else grep -Fx "$TARGET"; fi
}

# Enumerate matching repositories. Read into an array with a while-read loop
# rather than `mapfile` — the latter is Bash 4+, and macOS ships Bash 3.2, which
# this workstation tool must run on.
REPOS=()
while IFS= read -r _r; do
  [ -n "$_r" ] && REPOS+=("$_r")
done < <(
  aws ecr describe-repositories --region "$REGION" \
      --query 'repositories[].repositoryName' --output text 2>/dev/null \
    | tr '\t' '\n' | _match | sort || true
)

if [ "${#REPOS[@]}" -eq 0 ]; then
  echo "=== No repositories match '${SCOPE}' in $REGION — nothing to do. ==="
  exit 0
fi

# Count images per repo (best-effort, up to one page) for the plan. Track whether
# anything is actually there — treat a non-zero OR unknown ("?") count as "maybe
# has images" so we never skip on an ambiguous read.
echo "=== Repositories to clear ==="
HAVE_IMAGES=0
for repo in "${REPOS[@]}"; do
  n="$(aws ecr list-images --region "$REGION" --repository-name "$repo" \
         --query 'length(imageIds)' --output text 2>/dev/null || echo '?')"
  [ "$n" != "0" ] && HAVE_IMAGES=1
  printf '  %-45s %s image(s)\n' "$repo" "$n"
done

if [ "$HAVE_IMAGES" -eq 0 ]; then
  echo "=== All matching repositories are already empty — nothing to delete. ==="
  exit 0
fi

if [ "$DRY_RUN" -eq 1 ]; then
  echo "=== --dry-run: no images deleted. ==="
  exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  echo
  echo "This DELETES every image in the repositories above (the repos are kept)."
  printf "Type 'delete' to proceed: "
  read -r reply
  [ "$reply" = "delete" ] || { echo "Aborted."; exit 1; }
fi

# Delete every image in a repo, looping until empty so >100 images (paginated)
# are fully cleared. batch-delete-image accepts the JSON array list-images emits.
clear_repo() {
  local repo="$1" ids n total=0
  while :; do
    ids="$(aws ecr list-images --region "$REGION" --repository-name "$repo" \
             --query 'imageIds[*]' --output json)"
    [ "$ids" = "null" ] && ids="[]"
    [ "$ids" = "[]" ] && break
    n="$(printf '%s' "$ids" | grep -o imageDigest | wc -l | tr -d ' ')"
    aws ecr batch-delete-image --region "$REGION" --repository-name "$repo" \
        --image-ids "$ids" >/dev/null
    total=$((total + n))
  done
  echo "  cleared $repo ($total image(s))"
}

echo "=== Deleting ==="
for repo in "${REPOS[@]}"; do
  clear_repo "$repo"
done

echo "=== Done. ${#REPOS[@]} repositor$([ "${#REPOS[@]}" -eq 1 ] && echo y || echo ies) emptied in $REGION. ==="
echo "    Repositories kept — run deploy/ec2/build-and-push.sh to repopulate them."
