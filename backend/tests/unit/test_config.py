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


def test_settings_allows_local_totp_placeholder_as_dev_key() -> None:
    """Local env can use the documented placeholder as a dev-only Fernet key."""
    settings = Settings(
        ENVIRONMENT="local",
        TOTP_ENCRYPTION_KEY="replace-with-fernet-generate-key-output",
    )

    assert (
        settings.totp_encryption_key.get_secret_value()
        == "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )


# A valid Fernet key so the TOTP validator passes and the SECRET_KEY
# validator runs second — both are `model_validator(mode="after")` and
# pydantic short-circuits if the first raises.
_VALID_TOTP_KEY = "0123456789012345678901234567890123456789012="


def test_settings_rejects_dev_default_secret_key_outside_local() -> None:
    """Staging and production must override the dev SECRET_KEY value."""
    from pydantic import ValidationError

    try:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="dev-only-change-me",
            TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
        )
    except ValidationError as exc:
        assert "SECRET_KEY must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected dev SECRET_KEY validation to fail.")


def test_settings_rejects_placeholder_secret_key_outside_local() -> None:
    """The documented .env.example placeholder must not ship outside local."""
    from pydantic import ValidationError

    try:
        Settings(
            ENVIRONMENT="staging",
            SECRET_KEY="replace-with-openssl-rand-hex-32",
            TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
        )
    except ValidationError as exc:
        assert "SECRET_KEY must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected placeholder SECRET_KEY validation to fail.")


def test_settings_allows_dev_secret_key_in_local() -> None:
    """Local env keeps the dev SECRET_KEY default for convenience."""
    settings = Settings(ENVIRONMENT="local", SECRET_KEY="dev-only-change-me")

    assert settings.secret_key == "dev-only-change-me"


def test_settings_allows_real_secret_key_in_production() -> None:
    """A real SECRET_KEY (not a placeholder) passes the validator outside local."""
    settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a-real-openssl-rand-hex-32-value-with-entropy",
        TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
        STRIPE_SECRET_KEY="sk_live_real",
        STRIPE_WEBHOOK_SECRET="whsec_real",
    )

    assert settings.environment == "production"
    assert settings.secret_key.startswith("a-real")


def test_settings_rejects_placeholder_provider_secrets_outside_local() -> None:
    """Stripe secrets must be real outside local environments."""
    from pydantic import ValidationError

    try:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a-real-openssl-rand-hex-32-value-with-entropy",
            TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
            STRIPE_SECRET_KEY="replace-in-local-env",
            STRIPE_WEBHOOK_SECRET="whsec_real",
        )
    except ValidationError as exc:
        assert "Payment provider secrets must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected provider secret validation to fail.")
