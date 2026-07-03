from app.core import config
from app.core.config import Settings


def test_resolve_env_file_defaults_to_dotenv(monkeypatch) -> None:
    """With ENV_FILE unset, settings load the local `.env` file."""
    monkeypatch.delenv("ENV_FILE", raising=False)

    assert config._resolve_env_file() == ".env"


def test_resolve_env_file_honors_override(monkeypatch) -> None:
    """ENV_FILE selects an alternate env file (e.g. `.env.prod`) deliberately."""
    monkeypatch.setenv("ENV_FILE", ".env.prod")

    assert config._resolve_env_file() == ".env.prod"


def test_email_send_enabled_defaults_to_true() -> None:
    """Delivery defaults on, so an unset EMAIL_SEND_ENABLED (e.g. on Render) sends."""
    assert Settings.model_fields["email_send_enabled"].default is True


def test_email_send_enabled_can_be_disabled() -> None:
    """EMAIL_SEND_ENABLED=false routes lifecycle email to logging instead of Resend."""
    settings = Settings(EMAIL_SEND_ENABLED=False)

    assert settings.email_send_enabled is False


def test_settings_pins_all_redis_traffic_to_database_zero() -> None:
    """Upstash supports only DB 0, so Celery and app cache share database 0.

    App keys are namespaced by domain prefixes (refresh:, rate_limit:, etc.)
    and never collide with Celery's celery-task-meta-*/_kombu.* keyspace.
    """
    settings = Settings(REDIS_URL="redis://localhost:6379/7")

    assert settings.celery_broker_url == "redis://localhost:6379/0"
    assert settings.celery_result_backend == "redis://localhost:6379/0"
    assert settings.cache_redis_url == "redis://localhost:6379/0"


def test_settings_appends_ssl_cert_reqs_for_rediss_urls() -> None:
    """rediss:// (Upstash) must carry ssl_cert_reqs on every URL, cache included."""
    settings = Settings(REDIS_URL="rediss://default:pw@host.upstash.io:6379")

    expected = "rediss://default:pw@host.upstash.io:6379/0?ssl_cert_reqs=required"
    assert settings.celery_broker_url == expected
    assert settings.celery_result_backend == expected
    assert settings.cache_redis_url == expected


def test_settings_plain_redis_celery_urls_have_no_ssl_param() -> None:
    """Local redis:// (no TLS) must not gain ssl_cert_reqs params."""
    settings = Settings(REDIS_URL="redis://localhost:6379/3")

    assert settings.celery_broker_url == "redis://localhost:6379/0"
    assert settings.cache_redis_url == "redis://localhost:6379/0"
    assert "ssl_cert_reqs" not in settings.cache_redis_url


def test_settings_normalizes_database_urls_for_app_and_alembic() -> None:
    """FastAPI uses asyncpg URLs while Alembic receives a sync PostgreSQL URL."""
    settings = Settings(DATABASE_URL="postgresql://user:pass@host/auracles")

    assert settings.async_database_url == "postgresql+asyncpg://user:pass@host/auracles"
    assert settings.sync_database_url == "postgresql+psycopg://user:pass@host/auracles"


def test_async_url_translates_sslmode_for_asyncpg() -> None:
    """asyncpg rejects libpq's `sslmode`; the async URL must use `ssl` instead."""
    settings = Settings(DATABASE_URL="postgresql://u:p@host/db?sslmode=require")

    assert settings.async_database_url == "postgresql+asyncpg://u:p@host/db?ssl=require"
    # Alembic uses psycopg, which understands `sslmode` natively — keep it.
    assert (
        settings.sync_database_url == "postgresql+psycopg://u:p@host/db?sslmode=require"
    )


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


def test_settings_rejects_placeholder_payout_account_key_outside_local() -> None:
    """Staging and production must configure payout-account encryption."""
    from pydantic import ValidationError

    try:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a-real-openssl-rand-hex-32-value-with-entropy",
            TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
            STRIPE_SECRET_KEY="sk_live_real",
            STRIPE_WEBHOOK_SECRET="whsec_real",
        )
    except ValidationError as exc:
        assert "PAYOUT_ACCOUNT_ENCRYPTION_KEY must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected payout-account key validation to fail.")


# A valid Fernet key so the TOTP validator passes and the SECRET_KEY
# validator runs second — both are `model_validator(mode="after")` and
# pydantic short-circuits if the first raises.
_VALID_TOTP_KEY = "0123456789012345678901234567890123456789012="
_VALID_PAYOUT_ACCOUNT_KEY = "1234567890123456789012345678901234567890123="
_VALID_PARTNER_WEBHOOK_KEY = "2345678901234567890123456789012345678901234="


def test_settings_rejects_dev_default_secret_key_outside_local() -> None:
    """Staging and production must override the dev SECRET_KEY value."""
    from pydantic import ValidationError

    try:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="dev-only-change-me",
            TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
            PAYOUT_ACCOUNT_ENCRYPTION_KEY=_VALID_PAYOUT_ACCOUNT_KEY,
            PARTNER_WEBHOOK_ENCRYPTION_KEY=_VALID_PARTNER_WEBHOOK_KEY,
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
            PAYOUT_ACCOUNT_ENCRYPTION_KEY=_VALID_PAYOUT_ACCOUNT_KEY,
            PARTNER_WEBHOOK_ENCRYPTION_KEY=_VALID_PARTNER_WEBHOOK_KEY,
        )
    except ValidationError as exc:
        assert "SECRET_KEY must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected placeholder SECRET_KEY validation to fail.")


def test_settings_allows_dev_secret_key_in_local() -> None:
    """Local env keeps the dev SECRET_KEY default for convenience."""
    settings = Settings(ENVIRONMENT="local", SECRET_KEY="dev-only-change-me")

    assert settings.secret_key.get_secret_value() == "dev-only-change-me"


def test_settings_allows_real_secret_key_in_production() -> None:
    """A real SECRET_KEY (not a placeholder) passes the validator outside local."""
    settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a-real-openssl-rand-hex-32-value-with-entropy",
        TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
        PAYOUT_ACCOUNT_ENCRYPTION_KEY=_VALID_PAYOUT_ACCOUNT_KEY,
        PARTNER_WEBHOOK_ENCRYPTION_KEY=_VALID_PARTNER_WEBHOOK_KEY,
        STRIPE_SECRET_KEY="sk_live_real",
        STRIPE_WEBHOOK_SECRET="whsec_real",
    )

    assert settings.environment == "production"
    assert settings.secret_key.get_secret_value().startswith("a-real")


def test_settings_rejects_placeholder_provider_secrets_outside_local() -> None:
    """Stripe secrets must be real outside local environments."""
    from pydantic import ValidationError

    try:
        Settings(
            ENVIRONMENT="production",
            SECRET_KEY="a-real-openssl-rand-hex-32-value-with-entropy",
            TOTP_ENCRYPTION_KEY=_VALID_TOTP_KEY,
            PAYOUT_ACCOUNT_ENCRYPTION_KEY=_VALID_PAYOUT_ACCOUNT_KEY,
            PARTNER_WEBHOOK_ENCRYPTION_KEY=_VALID_PARTNER_WEBHOOK_KEY,
            STRIPE_SECRET_KEY="replace-in-local-env",
            STRIPE_WEBHOOK_SECRET="whsec_real",
        )
    except ValidationError as exc:
        assert "Payment provider secrets must be set outside local" in str(exc)
    else:
        raise AssertionError("Expected provider secret validation to fail.")
