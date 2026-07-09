"""Rate limiting middleware."""

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from core.cache import RateLimiter, get_valkey_client

logger = logging.getLogger(__name__)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limiting middleware using Valkey.

    Applies per-user rate limits based on the authenticated user.
    Falls back to per-IP rate limiting for unauthenticated requests.
    """

    def __init__(self, app, max_requests: int = 100, window_seconds: int = 60):  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._max_requests = max_requests
        self._window = window_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        try:
            client = await get_valkey_client()
            limiter = RateLimiter(
                client, max_requests=self._max_requests, window_seconds=self._window
            )

            # Use user ID if authenticated, otherwise use IP
            identifier = getattr(request.state, "user", None)
            if identifier is not None:
                key = f"user:{identifier.sub}"
            else:
                key = f"ip:{request.client.host if request.client else 'unknown'}"

            allowed, remaining = await limiter.is_allowed(key)

            if not allowed:
                return Response(
                    content='{"detail": "Rate limit exceeded"}',
                    status_code=429,
                    media_type="application/json",
                    headers={
                        "X-RateLimit-Limit": str(self._max_requests),
                        "X-RateLimit-Remaining": "0",
                        "Retry-After": str(self._window),
                    },
                )

            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(self._max_requests)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            return response

        except Exception:
            # If rate limiting fails (Valkey down), allow the request through
            logger.warning("Rate limiting unavailable, allowing request")
            return await call_next(request)
