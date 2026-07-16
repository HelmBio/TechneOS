"""Client/platform version-skew detection.

The CLI is distributed from this gateway (``/cli/simple/``), so a freshly
installed client always matches. Skew appears later, when the platform is
upgraded underneath a client that was installed against an older release.
"""

from __future__ import annotations

import re

# The platform's API version, as advertised to clients. This is the gateway
# package's version — the gateway is the API surface clients talk to.
PLATFORM_VERSION = "0.1.0"

WARNING_HEADER = "X-Client-Version-Warning"

_VERSION_RE = re.compile(r"^(\d+)\.(\d+)")


def _major_minor(version: str) -> tuple[int, int] | None:
    """Parse the leading ``major.minor`` from a version string, or None."""
    match = _VERSION_RE.match(version.strip())
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def compatibility_warning(
    client_version: str,
    platform_version: str = PLATFORM_VERSION,
    base_url: str = "",
) -> str:
    """Return a warning for an incompatible client, or "" if it's fine.

    Semver's compatibility unit differs either side of 1.0: while the platform
    is 0.x, a minor bump is allowed to break the API, so 0.1 and 0.2 are not
    interchangeable. From 1.0 on, only a major bump breaks, and a client that
    trails by a minor is expected to keep working — warning on that would cry
    wolf on every routine platform release.

    ``base_url`` makes the suggested command copy-pasteable; it is the URL the
    client already reached us on, so it is by construction the right one.
    """
    client = _major_minor(client_version)
    platform = _major_minor(platform_version)
    if client is None or platform is None:
        return ""

    if client == platform:
        return ""

    incompatible = client[0] != platform[0] or (platform[0] == 0 and client[1] != platform[1])
    if not incompatible:
        return ""

    index = f"{base_url.rstrip('/')}/cli/simple/" if base_url else "<platform-url>/cli/simple/"
    return (
        f"techneos-cli {client_version} does not match platform {platform_version}. "
        f"Reinstall the matching client: "
        f"pipx install --force --index-url {index} techneos-cli"
    )
