from app.core.config import Settings


def test_settings_derives_celery_and_cache_redis_databases() -> None:
    """Redis database 0 is reserved for Celery and database 1 for app cache."""
    settings = Settings(REDIS_URL="redis://localhost:6379/7")

    assert settings.celery_broker_url == "redis://localhost:6379/0"
    assert settings.celery_result_backend == "redis://localhost:6379/0"
    assert settings.cache_redis_url == "redis://localhost:6379/1"


def test_settings_normalizes_database_urls_for_app_and_alembic() -> None:
    """FastAPI uses asyncpg URLs while Alembic receives a sync PostgreSQL URL."""
    settings = Settings(DATABASE_URL="postgresql://user:pass@host/auracles")

    assert settings.async_database_url == "postgresql+asyncpg://user:pass@host/auracles"
    assert settings.sync_database_url == "postgresql+psycopg://user:pass@host/auracles"


def test_settings_ignores_script_only_environment_keys() -> None:
    """Script-only env vars should not break app settings loading."""
    settings = Settings(ADMIN_EMAIL="admin@auracles.space", ADMIN_PASSWORD="secret")

    assert settings.environment == "local"


def test_settings_parses_explicit_cors_origins() -> None:
    """CORS origins are parsed from a comma-separated allowlist."""
    settings = Settings(
        CORS_ALLOWED_ORIGINS="http://localhost:3000,https://auracles.space"
    )

    assert settings.cors_origin_list == [
        "http://localhost:3000",
        "https://auracles.space",
    ]


def test_settings_rejects_wildcard_cors_origins() -> None:
    """Wildcard CORS is forbidden because refresh cookies use credentials."""
    from pydantic import ValidationError

    try:
        Settings(CORS_ALLOWED_ORIGINS="*")
    except ValidationError as exc:
        assert "CORS_ALLOWED_ORIGINS cannot contain '*'" in str(exc)
    else:
        raise AssertionError("Expected wildcard CORS validation to fail.")


def test_settings_rejects_placeholder_totp_key_outside_local() -> None:
    """Staging and production must configure a real TOTP encryption key."""
    from pydantic import ValidationError

    try:
        Settings(ENVIRONMENT="production")
    except ValidationError as exc:
        assert "TOTP_ENCRYPTION_KEY must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected placeholder TOTP key validation to fail.")
