"""Flags CLI clients whose version is incompatible with this platform."""

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from gateway.client_version import WARNING_HEADER, compatibility_warning


class ClientVersionMiddleware(BaseHTTPMiddleware):
    """Adds a warning header when the calling client's version has drifted.

    Advisory only — the request is served either way. Clients that send no
    ``X-Client-Version`` (browsers, curl, the portal) are left alone.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        client_version = request.headers.get("X-Client-Version")
        if client_version:
            warning = compatibility_warning(client_version, base_url=str(request.base_url))
            if warning:
                response.headers[WARNING_HEADER] = warning

        return response
