"""Tests for core config module."""


def test_settings_defaults():
    """Settings should have sensible defaults when no .env overrides apply."""
    from core.config import Settings

    # Explicitly clear provider fields to test defaults are valid,
    # since the .env file may override them.
    settings = Settings(
        keycloak_url="",
        keycloak_client_id="",
        keycloak_client_secret="",
        oauth2_client_id="",
        oauth2_client_secret="",
        oauth2_authorization_url="",
        oauth2_token_url="",
        oauth2_redirect_url="",
    )
    assert settings.environment == "development"
    assert settings.postgres_port == 5432
    assert settings.keycloak_configured is False
    assert settings.oauth2_configured is False


def test_settings_database_url():
    """database_url property should construct a proper async URL."""
    from core.config import Settings

    settings = Settings(
        postgres_user="testuser",
        postgres_password="testpass",
        postgres_host="db.example.com",
        postgres_port=5433,
        postgres_db="testdb",
    )
    assert settings.database_url == (
        "postgresql+asyncpg://testuser:testpass@db.example.com:5433/testdb"
    )


def test_settings_database_url_sync():
    """database_url_sync should use the non-async driver."""
    from core.config import Settings

    settings = Settings(
        postgres_user="u",
        postgres_password="p",
        postgres_host="h",
        postgres_port=5432,
        postgres_db="d",
    )
    assert settings.database_url_sync == "postgresql://u:p@h:5432/d"
