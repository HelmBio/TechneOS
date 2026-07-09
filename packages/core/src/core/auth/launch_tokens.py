"""Mint short-lived JWT launch tokens used to hand off identity to Apps.

When an App registered with ``auth_mode='signed_jwt'`` is launched, the
platform mints a token signed with ``settings.app_launch_signing_key`` and
hands it to the App via URL query string (external mode) or postMessage
(embedded mode). The App verifies the signature, audience, and expiry
before trusting the claims.
"""

from datetime import UTC, datetime, timedelta

from jose import jwt

from core.config import get_settings
from core.exceptions import PlatformError

ALGORITHM = "HS256"


def mint_launch_token(
    *,
    user_id: str,
    org_id: str | None,
    email: str | None,
    audience: str,
    ttl_seconds: int = 300,
) -> tuple[str, datetime]:
    """Return ``(token, expires_at)`` for the given user/audience.

    Raises PlatformError when no signing key is configured.
    """
    settings = get_settings()
    key = settings.app_launch_signing_key
    if not key:
        raise PlatformError("App launch signing key is not configured")

    now = datetime.now(UTC)
    exp = now + timedelta(seconds=ttl_seconds)
    payload = {
        "sub": user_id,
        "org_id": org_id,
        "email": email,
        "aud": audience,
        "iss": "techneos-platform",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
    }
    token = jwt.encode(payload, key, algorithm=ALGORITHM)
    return token, exp
