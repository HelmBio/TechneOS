"""Application configuration via environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration for all platform services.

    Values are loaded from environment variables or a .env file.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Application ---
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = False
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:3000"  # comma-separated allowed origins
    # Directory the gateway serves the techneos-cli wheel from, resolved against
    # the process CWD — the app root both in the container and a source checkout.
    cli_wheel_dir: str = "cli-dist"
    secrets_encryption_key: str = (
        ""  # Fernet key for encrypting secrets at rest (API keys, bucket credentials)
    )

    # --- PostgreSQL ---
    postgres_user: str = "techneos"
    postgres_password: str = "techneos_dev_password"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "techneos"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        """Synchronous URL for Alembic migrations."""
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # --- MinIO ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "techneos-data"
    minio_secure: bool = False
    minio_region: str = "us-east-1"
    # Public HTTPS endpoint used only for presigned URL generation. When set,
    # presigned URLs use this hostname (HTTPS) instead of the internal endpoint,
    # so browsers on the public internet can fetch them. Leave empty in local dev.
    minio_public_endpoint: str = ""

    # --- Valkey ---
    valkey_url: str = "redis://localhost:6379/0"

    # --- Auth ---
    jwt_secret_key: str = "change-me-in-production-use-a-real-secret"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    internal_service_token: str = ""  # shared secret for Airflow→platform callbacks

    # --- Keycloak ---
    keycloak_url: str = ""
    keycloak_realm: str = "techneos"
    keycloak_client_id: str = ""
    keycloak_client_secret: str = ""
    keycloak_web_client_id: str = "techneos-web"
    keycloak_admin_user: str = "admin"
    keycloak_admin_password: str = "admin"
    keycloak_public_url: str = (
        ""  # external URL for OIDC endpoints (e.g. https://techneosapi.example.com/auth)
    )

    @property
    def keycloak_issuer_url(self) -> str:
        """OIDC issuer URL for the configured realm."""
        return f"{self.keycloak_url.rstrip('/')}/realms/{self.keycloak_realm}"

    @property
    def keycloak_openid_base(self) -> str:
        """Base URL for OpenID Connect endpoints."""
        return f"{self.keycloak_issuer_url}/protocol/openid-connect"

    @property
    def keycloak_configured(self) -> bool:
        """True when Keycloak env vars are fully populated."""
        return bool(self.keycloak_url and self.keycloak_client_id and self.keycloak_client_secret)

    @model_validator(mode="after")
    def _validate_keycloak_settings(self) -> "Settings":
        # Validate Keycloak config only when partially configured (some
        # vars set but not all).  Fully empty is fine — Keycloak is optional.
        has_any = bool(self.keycloak_url or self.keycloak_client_id or self.keycloak_client_secret)
        if has_any and not self.keycloak_configured:
            missing = []
            if not self.keycloak_url:
                missing.append("KEYCLOAK_URL")
            if not self.keycloak_client_id:
                missing.append("KEYCLOAK_CLIENT_ID")
            if not self.keycloak_client_secret:
                missing.append("KEYCLOAK_CLIENT_SECRET")
            if missing:
                raise ValueError(f"Keycloak partially configured — missing: {', '.join(missing)}")
        return self

    # --- Generic OAuth2 (e.g. PingFederate) ---
    oauth2_client_id: str = ""
    oauth2_client_secret: str = ""
    oauth2_authorization_url: str = ""
    oauth2_token_url: str = ""
    oauth2_redirect_url: str = ""
    oauth2_scopes: str = "openid"
    oauth2_introspect_url: str = ""
    oauth2_introspect_client_id: str = ""
    oauth2_introspect_client_secret: str = ""

    @property
    def oauth2_configured(self) -> bool:
        """True when the minimum OAuth2 env vars are fully populated."""
        return bool(
            self.oauth2_client_id
            and self.oauth2_client_secret
            and self.oauth2_authorization_url
            and self.oauth2_token_url
            and self.oauth2_redirect_url
        )

    @model_validator(mode="after")
    def _validate_oauth2_settings(self) -> "Settings":
        # Validate OAuth2 config when partially configured.
        has_any = bool(
            self.oauth2_client_id
            or self.oauth2_client_secret
            or self.oauth2_authorization_url
            or self.oauth2_token_url
            or self.oauth2_redirect_url
        )
        if has_any and not self.oauth2_configured:
            missing = []
            if not self.oauth2_client_id:
                missing.append("OAUTH2_CLIENT_ID")
            if not self.oauth2_client_secret:
                missing.append("OAUTH2_CLIENT_SECRET")
            if not self.oauth2_authorization_url:
                missing.append("OAUTH2_AUTHORIZATION_URL")
            if not self.oauth2_token_url:
                missing.append("OAUTH2_TOKEN_URL")
            if not self.oauth2_redirect_url:
                missing.append("OAUTH2_REDIRECT_URL")
            if missing:
                raise ValueError(f"OAuth2 partially configured — missing: {', '.join(missing)}")
        return self

    # --- LLM ---
    openai_api_key: str = ""
    openai_base_url: str = ""  # override for Azure / local proxies
    default_llm_model: str = "gpt-4o"
    default_llm_temperature: float = 0.1
    agent_max_iterations: int = 20

    # --- Dataset ---
    max_upload_file_size_mb: int = Field(
        default=100,
        description="Maximum file size in MB allowed for direct upload (larger files must use transfer)",
    )

    # --- Package Index (for pip-installable module tools) ---
    # Read from PYTHON_PACKAGE_INDEX_URL (the name used in .env and by
    # build_and_register.py) rather than the field-name default PACKAGE_INDEX_URL,
    # so services that load .env via pydantic see the configured dev/prod index.
    package_index_url: str = Field(
        default="http://devpi:8080/root/pypi/+simple/",
        validation_alias="PYTHON_PACKAGE_INDEX_URL",
        description="pip --index-url used to install pypi-type tools into the worker.",
    )
    package_index_publish_url: str = "http://devpi:8080/root/pypi/"
    package_index_user: str = ""
    package_index_password: str = ""

    @property
    def package_index_configured(self) -> bool:
        """True when a package index URL is set."""
        return bool(self.package_index_url)

    # --- Gateway (used by platform tools to make authenticated API calls) ---
    gateway_url: str = "http://localhost:8000"

    # --- Services ---
    gateway_port: int = 8000
    auth_service_port: int = 8001
    auth_service_url: str = "http://localhost:8001"
    dataset_service_port: int = 8002
    dataset_service_url: str = "http://localhost:8002"
    tool_service_port: int = 8003
    tool_service_url: str = "http://localhost:8003"
    task_service_port: int = 8008
    task_service_url: str = "http://localhost:8008"
    pipeline_service_port: int = 8004
    pipeline_service_url: str = "http://localhost:8004"
    agent_service_port: int = 8005
    agent_service_url: str = "http://localhost:8005"
    notification_service_port: int = 8006
    notification_service_url: str = "http://localhost:8006"
    app_service_port: int = 8007
    app_service_url: str = "http://localhost:8007"

    # --- Apps ---
    # Backend used by the App deployer worker to run embedded App containers.
    # `docker` uses the local Docker daemon (good for dev); `kubernetes` will
    # create Deployment+Service per App (not implemented in v1).
    app_deployer_backend: Literal["docker", "kubernetes"] = "docker"
    # Host:port the gateway uses to reach a container deployed by the
    # DockerDeployer. Defaults to host.docker.internal so containers run
    # by the deployer can be reached from the app_service process.
    app_deployer_host: str = "host.docker.internal"
    # Cookie Domain for the platform session cookie set on /login and read
    # on every subsequent request. Leave empty in dev — cookies scope to the
    # request's host (localhost), which is fine because cookies ignore the
    # port. In prod with a subdomain split (e.g. techneos.example.com for the web
    # frontend and techneosapi.example.com for the gateway), set ".example.com" so
    # the same cookie is sent on both origins (required for iframe loads via
    # the Next.js rewrite to authenticate).
    session_cookie_domain: str = ""
    # Symmetric key for signing short-lived JWT launch tokens
    # (auth_mode='signed_jwt'). Empty disables signed-JWT launches.
    app_launch_signing_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return cached application settings singleton."""
    return Settings()
