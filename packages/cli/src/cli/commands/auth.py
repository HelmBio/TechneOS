"""Auth commands — login, login-sso, logout, whoami, status."""

from __future__ import annotations

import typer

from cli.client import ApiError, api_get, api_post
from cli.config import clear_tokens, get_base_url, save_tokens, set_base_url
from cli.output import print_detail, print_error, print_success

auth_app = typer.Typer(name="auth", help="Authentication commands.", no_args_is_help=True)


@auth_app.command()
def login(
    email: str = typer.Option(..., prompt=True, help="Account email"),
    password: str = typer.Option(..., prompt=True, hide_input=True, help="Password"),
    url: str = typer.Option("", help="Platform URL (saves to config)"),
) -> None:
    """Log in with email + password and store access + refresh tokens."""
    if url:
        set_base_url(url)

    try:
        data = api_post(
            "/api/v1/auth/login",
            json={"email": email, "password": password, "auth_method": "local"},
        )
        save_tokens(data["access_token"], data["refresh_token"])
        print_success(f"Logged in as {email}")
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@auth_app.command("login-sso")
def login_sso(
    url: str = typer.Option("", help="Platform URL (saves to config)"),
    port: int = typer.Option(8085, help="Local callback server port"),
) -> None:
    """Log in via SSO (PKCE flow).

    Opens your browser to the configured SSO provider (Keycloak or OAuth2).
    After successful authentication the provider redirects back to a
    temporary local server which captures the authorization code and
    exchanges it for tokens.
    """
    if url:
        set_base_url(url)

    import hashlib
    import http.server
    import secrets
    import threading
    import urllib.parse
    import webbrowser

    import httpx

    base_url = get_base_url()

    # 1. Fetch auth discovery config from the platform
    try:
        resp = httpx.get(f"{base_url}/api/v1/auth/oidc/config", timeout=10.0)
        resp.raise_for_status()
        oidc = resp.json()
    except Exception as exc:
        print_error(f"Failed to fetch OIDC config: {exc}")
        raise typer.Exit(1) from None

    # Pick the available SSO provider: prefer OAuth2 (enterprise SSO), then Keycloak
    provider_name: str | None = None
    auth_endpoint = ""
    client_id = ""

    if oidc.get("oauth2"):
        provider_name = "oauth2"
        auth_endpoint = oidc["oauth2"]["authorization_endpoint"]
        client_id = oidc["oauth2"]["client_id"]
    elif oidc.get("keycloak"):
        provider_name = "keycloak"
        auth_endpoint = oidc["keycloak"]["authorization_endpoint"]
        client_id = oidc["keycloak"]["client_id"]

    if not provider_name:
        print_error("SSO is not enabled on this platform. Use `techneos auth login` instead.")
        raise typer.Exit(1) from None

    # 2. Generate PKCE code verifier + challenge
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    import base64

    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    state = secrets.token_urlsafe(16)
    redirect_uri = f"http://localhost:{port}/callback"

    # 3. Build the authorization URL
    params = urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": state,
        }
    )
    auth_url = f"{auth_endpoint}?{params}"

    # 4. Start a one-shot local HTTP server to capture the callback
    result: dict[str, str] = {}
    server_error: list[str] = []

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        """Handle the OIDC callback from Keycloak."""

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(parsed.query)

            if "error" in qs:
                desc = qs.get("error_description", qs["error"])[0]
                server_error.append(desc)
                self._respond("Login failed. You can close this tab.")
                return

            returned_state = qs.get("state", [""])[0]
            if returned_state != state:
                server_error.append("State mismatch — possible CSRF attack.")
                self._respond("Login failed (state mismatch). You can close this tab.")
                return

            code = qs.get("code", [""])[0]
            if not code:
                server_error.append("No authorization code received.")
                self._respond("Login failed. You can close this tab.")
                return

            result["code"] = code
            self._respond("Login successful! You can close this tab and return to the terminal.")

        def _respond(self, body: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = (
                "<!DOCTYPE html><html><head><title>TechneOS Login</title></head>"
                f"<body><h2>{body}</h2></body></html>"
            )
            self.wfile.write(html.encode())

        def log_message(self, format: str, *args: object) -> None:
            """Suppress default request logging."""

    server = http.server.HTTPServer(("127.0.0.1", port), CallbackHandler)
    server.timeout = 120  # 2-minute timeout

    typer.echo("Opening browser for SSO login...")
    typer.echo(f"If the browser does not open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    # Wait for exactly one request (the callback)
    server_thread = threading.Thread(target=server.handle_request, daemon=True)
    server_thread.start()
    server_thread.join(timeout=120)
    server.server_close()

    if server_error:
        print_error(server_error[0])
        raise typer.Exit(1) from None

    if "code" not in result:
        print_error("Timed out waiting for login callback.")
        raise typer.Exit(1) from None

    # 5. Exchange the authorization code for tokens via the backend
    try:
        data = api_post(
            "/api/v1/auth/token-exchange",
            json={
                "code": result["code"],
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
                "provider": provider_name,
            },
        )
        save_tokens(data["access_token"], data["refresh_token"])
        print_success("Logged in via SSO")
    except ApiError as e:
        print_error(f"Token exchange failed: {e.detail}")
        raise typer.Exit(1) from None


@auth_app.command()
def logout() -> None:
    """Clear stored tokens and revoke the Keycloak session if applicable."""
    from cli.config import load_tokens

    tokens = load_tokens()

    # Attempt to revoke the server-side session
    if tokens and tokens.get("refresh_token"):
        import contextlib

        with contextlib.suppress(Exception):
            api_post(
                "/api/v1/auth/logout",
                json={"refresh_token": tokens["refresh_token"]},
            )

    clear_tokens()
    print_success("Logged out")


@auth_app.command()
def whoami() -> None:
    """Show the current user profile."""
    from cli.client import require_auth

    require_auth()
    try:
        data = api_get("/api/v1/auth/me")
        print_detail(
            {
                "id": data["id"],
                "email": data["email"],
                "name": data["full_name"],
                "org_id": data.get("org_id", "—"),
                "role_id": data.get("role_id", "—"),
                "active": data["is_active"],
            },
            title="Current User",
        )
    except ApiError as e:
        print_error(e.detail)
        raise typer.Exit(1) from None


@auth_app.command()
def status() -> None:
    """Show login status and platform URL."""
    from cli.config import load_tokens

    url = get_base_url()
    tokens = load_tokens()
    logged_in = bool(tokens and tokens.get("access_token"))
    print_detail(
        {
            "platform_url": url,
            "logged_in": logged_in,
        },
        title="Auth Status",
    )
