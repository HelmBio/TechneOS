"""Shared client utilities for catalog registration scripts.

Authentication, environment resolution, env-file loading, and small API
helpers used by the catalog ``build_and_register.py`` / ``register.py``
scripts. Lives in ``management`` (the client/admin toolkit);
``core`` holds no API-client code.

Usage::

    from management.registration import (
        authenticate, resolve_api_url, resolve_org_id,
        find_resource_by_slug, auth_headers, add_env_arg, load_env_file,
    )

    load_env_file(args.env)             # build/publish config (CodeArtifact/ECR)
    api_url = resolve_api_url(args.env)  # gateway URL (single source of truth)
    token = authenticate(api_url, env=args.env)
    headers = auth_headers(token)
"""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv

from management.auth import (
    _check_api_token,
    _get_token_cache_path,
    _load_cached_token,
    _login,
    _save_cached_token,
)
from management.environment import Environment, resolve_environment

# Valid ``--env`` choices. The gateway URL for each comes from PLATFORM_API_URL in
# the sourced ``.env.<env>`` (management.environment), not from here.
ENV_CHOICES: tuple[str, ...] = ("local", "prod")

# Map an --env alias to its on-disk env file. Local dev uses the conventional
# project ``.env`` (also auto-loaded by Docker Compose and read by core Settings);
# prod/staging use ``.env.<env>``.
_ENV_FILE_NAME: dict[str, str] = {
    "local": ".env",
    "development": ".env",
    "dev": ".env",
    "prod": ".env.prod",
    "production": ".env.prod",
    "staging": ".env.staging",
}


def load_env_file(env: str | None) -> Path | None:
    """Load ``deploy/<file>`` (preferred) or the repo-root ``<file>`` for ``env``
    (``.env`` for local, ``.env.prod`` for prod).

    Carries **build/publish** config (CodeArtifact publish URL, ECR registry)
    for the ``build_and_register`` scripts — *not* the gateway URL, which comes
    from :func:`resolve_api_url`. Returns the loaded path, or ``None`` if no
    file was found (callers that don't need build config can ignore it).
    """
    if env is None:
        return None
    name = _ENV_FILE_NAME.get(env, f".env.{env}")
    repo_root = Path(__file__).resolve().parents[4]
    for candidate in (repo_root / "deploy" / name, repo_root / name):
        if candidate.exists():
            print(f"Loading environment from {candidate}")
            load_dotenv(dotenv_path=candidate, override=True)
            return candidate
    return None


def resolve_api_url(env: str, api_urls: dict[str, str] | None = None) -> str:
    """Resolve the API gateway URL from ``PLATFORM_API_URL`` (set in the sourced
    ``.env.<env>``), defaulting to the local stack. ``api_urls`` is unused (kept
    for call-site compatibility)."""
    return resolve_environment(env).api_url


def resolve_portal_url(env: str) -> str:
    """Resolve the web portal URL from ``PLATFORM_PORTAL_URL`` (sourced
    ``.env.<env>``), defaulting to the local stack."""
    return resolve_environment(env).portal_url


# ── Publish credentials (CodeArtifact token minting) ──────────────────────


def _is_codeartifact_url(url: str | None) -> bool:
    """True if ``url`` is an AWS CodeArtifact endpoint that needs a minted token.

    CodeArtifact endpoints look like
    ``<domain>-<owner>.d.codeartifact.<region>.amazonaws.com``.
    """
    if not url:
        return False
    hostname = urlparse(url).hostname or ""
    return ".d.codeartifact." in hostname and "amazonaws.com" in hostname


# ── Single-source package index (catalog repos configure just this) ────────
# PLATFORM_PYTHON_PACKAGE_INDEX (or uv's UV_DEFAULT_INDEX) is the package-index simple URL.
# The wheel publish endpoint, the CodeArtifact token coordinates, and the ECR
# registry are all DERIVED from it, so a standalone catalog repo configures one
# value instead of a publish URL + CODEARTIFACT_* + AWS_*.
# Explicit env vars still win when set — the monorepo deploy provides those
# directly and never sets PLATFORM_PYTHON_PACKAGE_INDEX, so its behavior is unchanged.


def package_index_url() -> str | None:
    """The configured package-index URL with any embedded credentials stripped.

    From ``PLATFORM_PYTHON_PACKAGE_INDEX`` (preferred) or ``UV_DEFAULT_INDEX`` (which
    ``bin/_ca_auth.sh`` may have injected ``aws:<token>@`` into). Returns ``None``
    when neither is set (e.g. the monorepo, which uses the explicit vars).
    """
    url = os.environ.get("PLATFORM_PYTHON_PACKAGE_INDEX") or os.environ.get("UV_DEFAULT_INDEX")
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.hostname and "@" in parsed.netloc:
        netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
        url = parsed._replace(netloc=netloc).geturl()
    return url


def _index_publish_url(index_url: str) -> str:
    """The upload endpoint for a simple-index URL (strip a trailing ``simple/``)."""
    base = index_url.rstrip("/")
    if base.endswith("/simple"):
        base = base[: -len("/simple")]
    return base + "/"


def _parse_codeartifact_coords(url: str | None) -> tuple[str, str, str] | None:
    """``(domain, owner, region)`` parsed from a CodeArtifact URL, or ``None``.

    Host form: ``<domain>-<owner>.d.codeartifact.<region>.amazonaws.com``.
    """
    if not _is_codeartifact_url(url):
        return None
    assert url is not None  # _is_codeartifact_url is False for None
    host = urlparse(url).hostname or ""
    left, _, right = host.partition(".d.codeartifact.")
    domain, _, owner = left.rpartition("-")
    region = right.split(".")[0]
    if domain and owner and region:
        return domain, owner, region
    return None


def _mint_codeartifact_token() -> str | None:
    """Mint a fresh CodeArtifact authorization token via ``boto3``.

    Returns the short-lived token, or ``None`` on any failure (boto3 missing,
    no AWS credentials, domain owner unset, ...). The caller decides how to
    handle ``None`` — for a CodeArtifact publish URL there is no usable
    fallback, so it errors out rather than reuse a stale token.

    NB: this intentionally duplicates the execution layer's CodeArtifact-token
    helper. ``management`` is the client/admin toolkit and goes through the
    gateway API — it must not import the execution (Airflow runtime) or ``core``
    (the gateway-side foundation), so the boto3 call is reproduced here.
    """
    try:
        import boto3
    except ImportError:
        print(
            "Warning: boto3 not installed — cannot mint CodeArtifact token",
            file=sys.stderr,
        )
        return None

    try:
        # Explicit env vars win; otherwise derive domain/owner/region from the
        # CodeArtifact index URL (PLATFORM_PYTHON_PACKAGE_INDEX / UV_DEFAULT_INDEX).
        coords = _parse_codeartifact_coords(package_index_url())
        region = os.getenv("AWS_REGION") or (coords[2] if coords else "us-east-1")
        client = boto3.client("codeartifact", region_name=region)
        domain = os.getenv("CODEARTIFACT_DOMAIN") or (coords[0] if coords else "techneos")
        # Airflow services set CODEARTIFACT_DOMAIN_OWNER; fall back to the generic
        # AWS_ACCOUNT_ID exported by deploy/.env.<env>, then the URL-derived owner.
        domain_owner = (
            os.getenv("CODEARTIFACT_DOMAIN_OWNER")
            or os.getenv("AWS_ACCOUNT_ID")
            or (coords[1] if coords else None)
        )
        if not domain_owner:
            print(
                "Warning: CODEARTIFACT_DOMAIN_OWNER / AWS_ACCOUNT_ID not set — "
                "cannot mint CodeArtifact token",
                file=sys.stderr,
            )
            return None
        response = client.get_authorization_token(
            domain=domain,
            domainOwner=domain_owner,
            # Token lifetime in seconds (default 1 hour); override PLATFORM_TOKEN_TTL_SECONDS.
            durationSeconds=int(os.environ.get("PLATFORM_TOKEN_TTL_SECONDS", "3600")),
        )
        return cast(str | None, response.get("authorizationToken"))
    except Exception as e:  # any boto3/AWS error → return None, caller errors out
        print(f"Warning: failed to mint CodeArtifact token: {e}", file=sys.stderr)
        return None


def resolve_publish_credentials() -> tuple[str, str, str]:
    """Resolve ``(publish_url, username, password)`` for ``uv publish``.

    For a CodeArtifact publish URL the credentials come **only** from a freshly
    minted token (username ``aws``) — the token baked into ``deploy/.env.<env>``
    expires within hours, so ``PYTHON_PACKAGE_USERNAME`` / ``PYTHON_PACKAGE_PASSWORD``
    are ignored there. If minting fails the script exits rather than retry the
    stale token (which would just 401). For any other index (local devpi) those
    two env vars are used directly, defaulting to ``devpi`` / ``devpi``.

    The publish URL is ``PYTHON_PACKAGE_PUBLISH_URL`` when set, else derived from
    the package index (``PLATFORM_PYTHON_PACKAGE_INDEX`` / ``UV_DEFAULT_INDEX`` minus the
    trailing ``simple/``), so a catalog repo configures only the index.
    """
    publish_url = os.environ.get("PYTHON_PACKAGE_PUBLISH_URL")
    if not publish_url:
        index = package_index_url()
        # Last-resort local devpi default; override TECHNEOS_DEFAULT_PUBLISH_URL.
        fallback = os.environ.get("TECHNEOS_DEFAULT_PUBLISH_URL", "http://localhost:3141/")
        publish_url = _index_publish_url(index) if index else fallback

    if _is_codeartifact_url(publish_url):
        token = _mint_codeartifact_token()
        if not token:
            print(
                "Error: could not mint a CodeArtifact token for publishing — "
                "check your AWS credentials and CODEARTIFACT_DOMAIN_OWNER / "
                "AWS_ACCOUNT_ID.",
                file=sys.stderr,
            )
            sys.exit(1)
        print("  Minted fresh CodeArtifact token for publish.")
        return publish_url, "aws", token  # CodeArtifact requires username "aws"

    username = os.environ.get("PYTHON_PACKAGE_USERNAME", "devpi")
    password = os.environ.get("PYTHON_PACKAGE_PASSWORD", "devpi")
    return publish_url, username, password


def build_wheel(package_dir: Path) -> Path:
    """Build ``package_dir``'s wheel with ``uv build --wheel`` and return its path.

    Exits on build failure or if no wheel is produced. The publish step is
    separate (:func:`build_and_publish_wheel`) so callers can build without
    publishing (e.g. ``--skip-publish``).
    """
    print("  Building wheel with `uv build` ...")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", "dist"],
        cwd=package_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(f"Error: uv build failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)

    wheels = sorted((package_dir / "dist").glob("*.whl"), key=os.path.getmtime, reverse=True)
    if not wheels:
        print("Error: no wheel produced in dist/", file=sys.stderr)
        sys.exit(1)
    return wheels[0]


def build_and_publish_wheel(package_dir: Path) -> str:
    """Build ``package_dir``'s wheel with ``uv build`` and publish it to the index.

    Shared by the platform packages that ship as wheels for catalog to depend on
    once it leaves the monorepo: ``techneos-tool-runtime`` and
    ``techneos-management``. Returns the publish URL — use it as the inventory
    ``registry_url``. Exits on build failure; a duplicate version is a no-op
    ("already exists").
    """
    wheel = build_wheel(package_dir)

    publish_url, username, password = resolve_publish_credentials()
    print(f"  Publishing {wheel.name} to {publish_url} ...")
    env = os.environ.copy()
    env["UV_PUBLISH_URL"] = publish_url
    env["UV_PUBLISH_USERNAME"] = username
    env["UV_PUBLISH_PASSWORD"] = password
    result = subprocess.run(
        ["uv", "publish", str(wheel)],
        cwd=package_dir,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    if result.returncode != 0:
        if "already exists" in result.stderr:
            print("  Wheel version already exists, skipping publish.")
        else:
            print(f"Warning: uv publish may have failed:\n{result.stderr}", file=sys.stderr)
    else:
        print(f"  Published {wheel.name}")
    return publish_url


def authenticate(
    api_url: str,
    env: str,
    email: str | None = None,
    password: str | None = None,
) -> str:
    """Obtain a JWT access token for the platform API.

    Shares the token cache with the ``management`` removal scripts:
    the token lives at ``~/.techneos/{canonical-env}_token.json`` (e.g. ``production``)
    in ``management.auth``'s JSON format, so a token obtained by either the
    register scripts or ``bin/*_removal.sh`` is reused by both. The cached token
    is validated server-side via ``/auth/me``.
    """
    env_name = resolve_environment(env).name
    cached = _load_cached_token(env_name)
    if cached:
        token, _base_url = cached
        info = _check_api_token(token, api_url)
        if info is not None:
            print(f"Using token from {_get_token_cache_path(env_name)}")
            print(f"Authenticated as {info.email} (role: {info.role})")
            return token

    if not email:
        email = input("Admin email: ")
    if not password:
        password = getpass.getpass("Password: ")

    token = _login(api_url, email, password)
    _save_cached_token(token, api_url, env_name)
    info = _check_api_token(token, api_url)
    if info is not None:
        print(f"Authenticated as {info.email} (role: {info.role})")
    else:
        print(f"Authenticated as {email}")
    return token


def resolve_org_id(api_url: str, headers: dict[str, Any]) -> str:
    """Extract the user's organization ID from the /auth/me endpoint."""
    resp = httpx.get(f"{api_url}/api/v1/auth/me", headers=headers)
    if not resp.is_success:
        print(
            f"Error: failed to get user info (HTTP {resp.status_code})",
            file=sys.stderr,
        )
        sys.exit(1)
    org_id = resp.json().get("org_id")
    if not org_id:
        print("Error: user is not associated with an organization", file=sys.stderr)
        sys.exit(1)
    return cast(str, org_id)


def find_resource_by_slug(
    api_url: str,
    headers: dict[str, Any],
    endpoint: str,
    slug: str,
) -> str | None:
    """Look up any resource by slug from a paginated list endpoint.

    Returns the resource id or ``None`` if not found.
    """
    resp = httpx.get(f"{api_url}{endpoint}", headers=headers)
    if not resp.is_success:
        return None
    data = resp.json()
    for item in data.get("items", []):
        if item.get("slug") == slug:
            return cast(str | None, item["id"])
    return None


# ─────────────────────────────────────────────────────────────────────────────
# High-level orchestration (Layer 1) — shared by the platform wheel scripts AND
# the catalog `register_*` orchestrators in ``management.catalog``. Composes the
# primitives above so each build_and_register.py is config + a couple of calls.
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class PackageMeta:
    """Coordinates read from a package's ``pyproject.toml`` (``[project]`` + ``[tool.techneos]``)."""

    name: str
    version: str
    entry_point: str | None = None
    docker_image: str | None = None


def read_package_meta(package_dir: Path) -> PackageMeta:
    """Read ``name``/``version`` (+ optional ``[tool.techneos]`` ``entry_point``/``docker_image``)."""
    data = tomllib.loads((package_dir / "pyproject.toml").read_text())
    project = data["project"]
    techneos = data.get("tool", {}).get("techneos", {})
    return PackageMeta(
        name=project["name"],
        version=project["version"],
        entry_point=techneos.get("entry_point"),
        docker_image=techneos.get("docker_image"),
    )


@dataclass
class Session:
    """An authenticated registration session: resolved env + auth headers.

    ``env_arg`` is the raw ``--env`` value (e.g. ``"local"``/``"prod"``) that the
    registry/ECR helpers (``resolve_image_repo``, ``ecr_login``, …) expect, distinct
    from the canonical ``env.name``.
    """

    env: Environment
    env_arg: str | None
    api_url: str
    headers: dict[str, Any]


def start_session(args: argparse.Namespace) -> Session:
    """The shared ``main()`` preamble: load the dotenv, resolve env, auth.

    Used by every build/register script (platform wheels and catalog items).
    ``args`` must carry ``.env``; ``.email``/``.password`` are honored when present
    (non-interactive CI), otherwise auth falls back to the cached token / prompt.
    org_id is resolved on demand by the catalog orchestrators — platform wheels
    don't need it.
    """
    env_arg = getattr(args, "env", None)
    # Load the .env.<env> first so PLATFORM_API_URL / PLATFORM_PORTAL_URL are set
    # before resolve_environment reads them.
    load_env_file(env_arg)
    env = resolve_environment(env_arg)
    print(f"Environment: {env}")
    print(flush=True)
    token = authenticate(
        env.api_url, env.name, getattr(args, "email", None), getattr(args, "password", None)
    )
    return Session(env=env, env_arg=env_arg, api_url=env.api_url, headers=auth_headers(token))


def publish_wheel_and_record(
    session: Session,
    package_dir: Path,
    *,
    origin: str,
    entry_point: str | None = None,
    publish: bool = True,
) -> str:
    """Build the wheel, and (when ``publish``) push it to the index + record it.

    Returns the package version. ``publish=False`` builds only (``--skip-publish``):
    no index push, no inventory record. When publishing, the artifact is recorded
    *before* any version/definition that references it (hard-validated).
    ``origin`` is ``"platform"`` (the wheels) or ``"catalog"`` (catalog items).
    """
    meta = read_package_meta(package_dir)
    if publish:
        registry_url = build_and_publish_wheel(package_dir)
        record_artifact(
            session.api_url,
            session.headers,
            kind="wheel",
            origin=origin,
            name=meta.name,
            version=meta.version,
            registry_url=registry_url,
            metadata={"entry_point": entry_point} if entry_point else None,
        )
    else:
        build_wheel(package_dir)
        print("  Built wheel (not published — --skip-publish).")
    return meta.version


def current_git_sha() -> str | None:
    """Return the short git commit sha of the repo, or ``None`` outside a checkout."""
    result = subprocess.run(
        ["git", "rev-parse", "--short=12", "HEAD"],
        text=True,
        check=False,
        capture_output=True,
    )
    sha = result.stdout.strip()
    return sha or None


def record_artifact(
    api_url: str,
    headers: dict[str, Any],
    *,
    kind: str,
    origin: str,
    name: str,
    version: str,
    registry_url: str | None = None,
    digest: str | None = None,
    source_commit_sha: str | None = None,
    metadata: dict[str, Any] | None = None,
    fatal: bool = True,
) -> None:
    """Record a built & published artifact in the platform inventory (upsert).

    Call this *after* a successful publish/push and *before* registering the
    tool version that references it — tool-version creation is hard-validated
    against the inventory, so an unrecorded wheel/image is rejected (422).

    ``kind`` is ``"wheel"`` or ``"docker_image"``; ``origin`` is the provenance
    — ``"catalog"`` (a registered tool/agent/app) or ``"platform"`` (a
    service/runtime image the platform builds), defaulting to ``"other"``. The
    call is idempotent on ``(kind, name, version, registry_url)``.

    ``fatal=True`` exits on failure (the default for tool scripts, where the
    following version create would 422 anyway). Agent/app scripts that record
    only for inventory completeness can pass ``fatal=False``.
    """
    payload = {
        "kind": kind,
        "origin": origin,
        "name": name,
        "version": version,
        "registry_url": registry_url,
        "digest": digest,
        "source_commit_sha": source_commit_sha or current_git_sha(),
        "metadata": metadata or {},
    }
    resp = httpx.post(
        f"{api_url}/api/v1/compute-artifacts", json=payload, headers=headers
    )
    if resp.status_code in (200, 201):
        print(f"  Recorded artifact in inventory: {kind} {name} {version}")
        return
    msg = (
        f"failed to record artifact {kind} {name} {version} "
        f"(HTTP {resp.status_code}): {resp.text}"
    )
    if fatal:
        print(f"Error: {msg}", file=sys.stderr)
        sys.exit(1)
    print(f"Warning: {msg}", file=sys.stderr)


def auth_headers(token: str, content_type: str | None = "application/json") -> dict[str, str]:
    """Standard HTTP headers for API requests.

    Drop ``Content-Type`` for multipart uploads (httpx sets it automatically)::

        headers = auth_headers(token, content_type=None)
        client.post(url, headers=headers, files={...})
    """
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def add_env_arg(parser: argparse.ArgumentParser) -> None:
    """Add the standard ``--env`` argument."""
    parser.add_argument(
        "--env",
        choices=list(ENV_CHOICES),
        default="local",
        help="Target environment (default: local)",
    )


def add_auth_args(parser: argparse.ArgumentParser) -> None:
    """Add standard ``--email`` and ``--password`` arguments."""
    parser.add_argument(
        "--email",
        default=None,
        help="Admin email (prompts interactively if omitted)",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Admin password (prompts interactively if omitted)",
    )


def add_upsert_arg(parser: argparse.ArgumentParser) -> None:
    """Add the standard ``--upsert`` argument."""
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="Recreate the resource if it already exists",
    )


def make_publish_parser(description: str) -> argparse.ArgumentParser:
    """Parser for a wheel-only platform package's build_and_register.py.

    Standard ``--env`` + auth args + ``--skip-register`` (publish the wheel but
    don't record it in the inventory). Used by the techneos-tool-runtime / techneos-management
    publish scripts.
    """
    parser = argparse.ArgumentParser(description=description)
    add_env_arg(parser)
    add_auth_args(parser)
    parser.add_argument(
        "--skip-register",
        action="store_true",
        help="Publish the wheel but do not record it in the artifact inventory",
    )
    return parser


# ── Docker / ECR helpers ──────────────────────────────────────────────────


def _run_or_exit(
    cmd: list[str] | str,
    *,
    shell: bool = False,
    errmsg: str = "Command failed",
) -> None:
    result = subprocess.run(cmd, shell=shell, text=True, check=False)
    if result.returncode != 0:
        print(f"Error: {errmsg}", file=sys.stderr)
        sys.exit(1)


def resolve_ecr_registry(env: str) -> str | None:
    """Return the ECR registry host for prod, or ``None`` for local.

    Account/region come from ``AWS_ACCOUNT_ID`` / ``AWS_REGION`` when set, else
    are derived from the CodeArtifact package index (``PLATFORM_PYTHON_PACKAGE_INDEX`` /
    ``UV_DEFAULT_INDEX``) — same AWS account + region as the wheel registry, so a
    catalog repo configures only the index. Exits if neither is available.
    """
    if env != "prod":
        return None
    coords = _parse_codeartifact_coords(package_index_url())
    account = os.environ.get("AWS_ACCOUNT_ID") or (coords[1] if coords else None)
    if not account:
        print(
            "Error: cannot resolve the AWS account for --env=prod — set "
            "AWS_ACCOUNT_ID or PLATFORM_PYTHON_PACKAGE_INDEX (CodeArtifact URL).",
            file=sys.stderr,
        )
        sys.exit(1)
    region = os.environ.get("AWS_REGION") or (coords[2] if coords else "us-east-1")
    return f"{account}.dkr.ecr.{region}.amazonaws.com"


def resolve_image_repo(env: str) -> str:
    """Return the image repository prefix for ``env``.

    Returns ``"{registry}/techneos"`` for prod (e.g.
    ``123456789012.dkr.ecr.us-east-1.amazonaws.com/techneos``), or just ``"techneos"``
    for local. Combine with a slug: ``f"{resolve_image_repo(env)}/{TOOL_SLUG}"``.
    """
    registry = resolve_ecr_registry(env)
    return f"{registry}/techneos" if registry else "techneos"


def ecr_login(env: str) -> None:
    """Authenticate the local Docker daemon against ECR (prod only)."""
    registry = resolve_ecr_registry(env)
    if not registry:
        return
    region = registry.split(".")[3]
    print(f"  Logging in to ECR ({registry}) ...")
    _run_or_exit(
        f"aws ecr get-login-password --region {region}"
        f" | docker login --username AWS --password-stdin {registry}",
        shell=True,
        errmsg="ECR login failed",
    )


def ensure_ecr_repo(env: str, repo: str) -> None:
    """Create the ECR repository ``repo`` if it does not already exist (prod only).

    ``repo`` is the repository name without the registry prefix, e.g.
    ``"techneos/dataset-profiler"``.
    """
    registry = resolve_ecr_registry(env)
    if not registry:
        return
    region = registry.split(".")[3]
    check = subprocess.run(
        [
            "aws", "ecr", "describe-repositories",
            "--repository-names", repo,
            "--region", region,
        ],
        text=True,
        check=False,
        capture_output=True,
    )
    if check.returncode != 0:
        print(f"  Creating ECR repo: {repo} ...")
        _run_or_exit(
            [
                "aws", "ecr", "create-repository",
                "--repository-name", repo,
                "--region", region,
            ],
            errmsg=f"Failed to create ECR repo {repo}",
        )
    else:
        print(f"  ECR repo exists: {repo}")


def build_and_push_image(
    image: str,
    context: Path,
    version: str,
    env: str,
    *,
    push: bool = True,
    build_args: dict[str, str] | None = None,
) -> None:
    """Build a Docker image, optionally push to ECR, and re-tag locally.

    ``image`` is the bare ``namespace/name`` without a registry prefix, e.g.
    ``"techneos/dataset-profiler"``.  That name is what the API stores and what
    the Airflow worker uses when it runs the container via the host daemon.

    **prod + push:** builds for ``linux/amd64`` via ``docker buildx``, pushes
    both ``:{version}`` and ``:latest`` to ECR, then pulls the versioned tag
    back to the local daemon and re-tags it as ``{image}:{version}`` /
    ``{image}:latest`` so the local Airflow worker can use it immediately.
    ``BASE_REGISTRY`` is injected automatically so the Dockerfile's ``FROM``
    can resolve ``techneos/tool-runtime`` from ECR during the build.

    **local / no push:** plain ``docker build`` tagged ``:{version}`` and
    ``:latest`` in the local daemon — no cross-arch, no ECR.
    """
    registry = resolve_ecr_registry(env)
    extra_args: list[str] = []
    for k, v in (build_args or {}).items():
        extra_args += ["--build-arg", f"{k}={v}"]

    if registry and push:
        ecr_image = f"{registry}/{image}"
        extra_args += ["--build-arg", f"BASE_REGISTRY={registry}/"]
        print(f"  Building & pushing {ecr_image}:{version} (linux/amd64) ...")
        _run_or_exit(
            [
                "docker", "buildx", "build",
                "--platform", "linux/amd64",
                "--push",
                "-t", f"{ecr_image}:{version}",
                "-t", f"{ecr_image}:latest",
                *extra_args,
                str(context),
            ],
            errmsg=f"docker buildx build+push failed for {ecr_image}",
        )
        # Pull back and re-tag locally so the Airflow DockerBackend can run
        # the image immediately without a separate deploy step.
        # --platform linux/amd64 is required on Apple Silicon: the manifest list
        # only has an amd64 entry (we built with --platform linux/amd64), so a
        # bare pull would try to match arm64 and fail.
        print(f"  Pulling {ecr_image}:{version} to local daemon ...")
        _run_or_exit(
            ["docker", "pull", "--platform", "linux/amd64", f"{ecr_image}:{version}"],
            errmsg=f"docker pull failed for {ecr_image}:{version}",
        )
        for tag in (version, "latest"):
            _run_or_exit(
                ["docker", "tag", f"{ecr_image}:{version}", f"{image}:{tag}"],
                errmsg=f"docker tag failed for {image}:{tag}",
            )
        print(f"  Tagged locally as {image}:{version} and {image}:latest")
    else:
        print(f"  Building {image}:{version} (local) ...")
        _run_or_exit(
            [
                "docker", "build",
                "-t", f"{image}:{version}",
                "-t", f"{image}:latest",
                *extra_args,
                str(context),
            ],
            errmsg=f"docker build failed for {image}",
        )
        print(f"  Built {image}:{version}")


def pull_tool_image_on_ec2(env: str, ecr_image: str, version: str) -> None:
    """Pre-cache a freshly-pushed ECR image on the EC2 host daemon via SSM.

    After ``docker buildx build --push`` the image lives in ECR but not on the
    EC2 host daemon. The Airflow worker stores the **full ECR URL** as the
    tool's ``docker_image`` and pulls it on demand (the host's
    amazon-ecr-credential-helper authenticates automatically via the instance
    IAM role), so this pre-cache only speeds up the first run — it is not
    required for correctness. ``docker image prune -af`` on the next deploy will
    drop it again, and the worker will simply re-pull from ECR.

    No ``docker login`` is issued: the credential helper handles auth, and an
    explicit login would fail with "not implemented" (the helper has no
    credential-store backend). Requires ``EC2_INSTANCE_ID`` in the environment
    (from ``deploy/.env.prod``); if unset, prints the manual command and skips.
    """
    if env != "prod":
        return
    instance_id = os.environ.get("EC2_INSTANCE_ID")
    if not instance_id:
        print(
            "  Note: EC2_INSTANCE_ID not set in deploy/.env.prod — skipping EC2 pre-pull.\n"
            "  Not fatal: the worker pulls the ECR image on demand. To pre-cache:\n"
            f"    docker pull {ecr_image}:latest",
            file=sys.stderr,
        )
        return

    region = os.environ.get("AWS_REGION", "us-east-1")
    commands = [
        f"docker pull {ecr_image}:{version}",
        f"docker pull {ecr_image}:latest",
    ]

    try:
        import boto3
        ssm = boto3.client("ssm", region_name=region)
        print(f"  Pre-caching {ecr_image} on EC2 {instance_id} via SSM ...")
        resp = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": commands},
        )
        cmd_id = resp["Command"]["CommandId"]
        print(f"  SSM command sent: {cmd_id}")
        print(
            f"  Check: aws ssm get-command-invocation"
            f" --command-id {cmd_id} --instance-id {instance_id}"
        )
    except Exception as exc:
        print(f"  Note: SSM pre-pull failed (non-fatal): {exc}", file=sys.stderr)


def build_image_and_record(
    session: Session,
    *,
    slug: str,
    package_dir: Path,
    version: str,
    origin: str,
    build_image: str | None = None,
    skip_build: bool = False,
    skip_push: bool = False,
    fatal: bool = True,
) -> str:
    """Build a catalog Docker image, push to ECR (+ pre-cache on EC2) for non-local
    envs, and record it in the inventory. Returns the stored image reference
    (``{repo}/<slug>`` — full ECR URL for prod, bare ``techneos/<slug>`` for local), the
    value the worker / app-service pulls.

    Shared by container tools and embedded apps — both build an image the same way
    (``buildx`` cross-arch + ECR push for prod; plain build for local). ``build_image``
    is the bare local build tag (defaults to ``techneos/<slug>``). ``fatal`` governs the
    inventory record (tool versions are hard-validated → fatal; apps are not).
    ``skip_build`` skips the whole step (re-register against an already-pushed image).
    """
    env = session.env_arg or "local"
    image_ref = f"{resolve_image_repo(env)}/{slug}"
    if skip_build:
        return image_ref
    do_push = not skip_push and env != "local"
    if do_push:
        ecr_login(env)
        ensure_ecr_repo(env, f"techneos/{slug}")
    build_and_push_image(build_image or f"techneos/{slug}", package_dir, version, env, push=do_push)
    if do_push:
        pull_tool_image_on_ec2(env, ecr_image=image_ref, version=version)
    record_artifact(
        session.api_url,
        session.headers,
        kind="docker_image",
        origin=origin,
        name=image_ref,
        version=version,
        registry_url=resolve_ecr_registry(env),
        fatal=fatal,
    )
    return image_ref
