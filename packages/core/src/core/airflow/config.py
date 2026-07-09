"""Airflow connection configuration from environment variables."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class AirflowSettings(BaseSettings):
    """Airflow REST API connection settings.

    All values can be overridden via environment variables prefixed with
    ``AIRFLOW_``.  When Airflow is not configured (``airflow_base_url``
    is empty) the orchestrator should fall back to a no-op / local mode.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    airflow_base_url: str = ""
    airflow_username: str = "airflow"
    airflow_password: str = "airflow"
    airflow_api_prefix: str = "/api/v1"
    airflow_timeout_seconds: int = 30

    # The Airflow DAG id used for TechneOS pipeline runs. The execution package
    # registers a dynamic DAG under this id — the Airflow DAG factory reads
    # the same AIRFLOW_DAG_ID env var directly (it can't import core at runtime).
    airflow_dag_id: str = "techneos_airflow_pipeline"

    # Platform callback URL that Airflow tasks use to report status.
    # Typically the gateway URL so auth middleware is applied.
    # Use http://host.docker.internal:8000 when Airflow runs in Docker.
    platform_callback_url: str = "http://host.docker.internal:8000"

    @property
    def api_url(self) -> str:
        """Full base URL for the Airflow REST API."""
        return f"{self.airflow_base_url.rstrip('/')}{self.airflow_api_prefix}"

    @property
    def configured(self) -> bool:
        """True when Airflow connection is available."""
        return bool(self.airflow_base_url)


@lru_cache
def get_airflow_settings() -> AirflowSettings:
    """Return cached Airflow settings singleton."""
    return AirflowSettings()
