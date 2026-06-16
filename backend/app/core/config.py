"""Application configuration.

Loads environment variables into a typed Pydantic settings object and
normalises connection URLs (async Postgres dialect, Redis database
indices). All other modules import settings via `get_settings()`.

Maps to: pre-scale infra design Section 4 (secrets management) and
TDD Section 5 (configuration).
"""

import os
from functools import lru_cache
from typing import Literal, Self
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_TOTP_ENCRYPTION_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
DEV_PAYOUT_ACCOUNT_ENCRYPTION_KEY = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB="
DEV_PARTNER_WEBHOOK_ENCRYPTION_KEY = "CCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCCC="
PLACEHOLDER_TOTP_ENCRYPTION_KEY = "replace-with-fernet-generate-key-output"
PLACEHOLDER_PAYOUT_ACCOUNT_ENCRYPTION_KEY = "replace-with-fernet-generate-key-output"
PLACEHOLDER_PARTNER_WEBHOOK_ENCRYPTION_KEY = "replace-with-fernet-generate-key-output"
DEV_SECRET_KEY = "dev-only-change-me"
PLACEHOLDER_SECRET_KEY = "replace-with-openssl-rand-hex-32"
PLACEHOLDER_PROVIDER_SECRET = "replace-in-local-env"


def _resolve_env_file() -> str:
    """Return the dotenv file to load (`.env` by default).

    Set ``ENV_FILE=.env.prod`` to deliberately point a local process at
    remote/production values. Tests never rely on this; they pin localhost
    values in conftest regardless of the selected file.
    """
    return os.getenv("ENV_FILE", ".env")


def _celery_redis_url(url: str, database: int) -> str:
    """Build a Celery broker/backend URL, adding TLS verification for ``rediss://``.

    Celery (kombu) refuses a ``rediss://`` URL that lacks ``ssl_cert_reqs``. Upstash
    presents valid certificates, so we require verification (``CERT_REQUIRED``).
    Plain ``redis://`` (local dev) is returned untouched.
    """
    parsed = urlsplit(url)
    parsed = parsed._replace(path=f"/{database}")
    if parsed.scheme == "rediss":
        query = dict(parse_qsl(parsed.query))
        query.setdefault("ssl_cert_reqs", "required")
        parsed = parsed._replace(query=urlencode(query))
    return urlunsplit(parsed)


def _to_async_postgres_url(url: str) -> str:
    if not (url.startswith("postgresql://") or url.startswith("postgresql+asyncpg://")):
        return url
    parsed = urlsplit(url)
    query = dict(parse_qsl(parsed.query))
    # asyncpg has no `sslmode`; translate libpq's value to its `ssl` parameter.
    sslmode = query.pop("sslmode", None)
    if sslmode and "ssl" not in query:
        query["ssl"] = sslmode
    parsed = parsed._replace(scheme="postgresql+asyncpg", query=urlencode(query))
    return urlunsplit(parsed)


def _to_sync_postgres_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=_resolve_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(default="local", alias="ENVIRONMENT")
    log_format: str = Field(default="text", alias="LOG_FORMAT")
    database_url: str = Field(
        default="postgresql+asyncpg://auracles:secret@localhost:5432/auracles",
        alias="DATABASE_URL",
    )
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    secret_key: SecretStr = Field(
        default=SecretStr(DEV_SECRET_KEY),
        alias="SECRET_KEY",
    )
    totp_encryption_key: SecretStr = Field(
        default=SecretStr(DEV_TOTP_ENCRYPTION_KEY),
        alias="TOTP_ENCRYPTION_KEY",
    )
    payout_account_encryption_key: SecretStr = Field(
        default=SecretStr(DEV_PAYOUT_ACCOUNT_ENCRYPTION_KEY),
        alias="PAYOUT_ACCOUNT_ENCRYPTION_KEY",
    )
    partner_webhook_encryption_key: SecretStr = Field(
        default=SecretStr(DEV_PARTNER_WEBHOOK_ENCRYPTION_KEY),
        alias="PARTNER_WEBHOOK_ENCRYPTION_KEY",
    )
    cors_allowed_origins: str = Field(
        default="http://localhost:3000",
        alias="CORS_ALLOWED_ORIGINS",
    )
    cookie_samesite: Literal["strict", "none"] = Field(
        default="strict",
        alias="COOKIE_SAMESITE",
    )
    trust_proxy_headers: bool = Field(
        default=False,
        alias="TRUST_PROXY_HEADERS",
    )
    aws_access_key_id: SecretStr | None = Field(
        default=None, alias="AWS_ACCESS_KEY_ID"
    )
    aws_secret_access_key: SecretStr | None = Field(
        default=None, alias="AWS_SECRET_ACCESS_KEY"
    )
    aws_default_region: str = Field(default="us-east-1", alias="AWS_DEFAULT_REGION")
    aws_endpoint_url: str | None = Field(default=None, alias="AWS_ENDPOINT_URL")
    s3_artifacts_bucket: str = Field(
        default="auracles-artifacts-dev", alias="S3_ARTIFACTS_BUCKET"
    )
    s3_avatars_bucket: str = Field(
        default="auracles-avatars-dev", alias="S3_AVATARS_BUCKET"
    )
    s3_reports_bucket: str = Field(
        default="auracles-reports-dev", alias="S3_REPORTS_BUCKET"
    )
    s3_thumbnails_bucket: str = Field(
        default="auracles-thumbnails-dev", alias="S3_THUMBNAILS_BUCKET"
    )
    resend_from_address: str = Field(
        default="noreply@auracles.space", alias="RESEND_FROM_ADDRESS"
    )
    resend_api_key: SecretStr | None = Field(default=None, alias="RESEND_API_KEY")
    # Gate live email delivery. Default True so an unset value (e.g. on Render)
    # still sends; set EMAIL_SEND_ENABLED=false locally to log emails instead of
    # calling Resend (avoids burning the Resend daily quota during flow testing).
    email_send_enabled: bool = Field(default=True, alias="EMAIL_SEND_ENABLED")
    stripe_secret_key: SecretStr | None = Field(
        default=None, alias="STRIPE_SECRET_KEY"
    )
    stripe_webhook_secret: SecretStr | None = Field(
        default=None, alias="STRIPE_WEBHOOK_SECRET"
    )
    paystack_secret_key: SecretStr | None = Field(
        default=None, alias="PAYSTACK_SECRET_KEY"
    )
    paystack_webhook_secret: SecretStr | None = Field(
        default=None, alias="PAYSTACK_WEBHOOK_SECRET"
    )
    brave_search_api_key: SecretStr | None = Field(
        default=None, alias="BRAVE_SEARCH_API_KEY"
    )
    brave_search_base_url: str = Field(
        default="https://api.search.brave.com/res/v1/web/search",
        alias="BRAVE_SEARCH_BASE_URL",
    )
    ocr_tesseract_command: str = Field(
        default="tesseract",
        alias="OCR_TESSERACT_COMMAND",
    )
    ocr_timeout_seconds: int = Field(default=60, alias="OCR_TIMEOUT_SECONDS")
    ocr_pdf_dpi: int = Field(default=200, alias="OCR_PDF_DPI")
    ocr_tesseract_page_segmentation_mode: str = Field(
        default="6",
        alias="OCR_TESSERACT_PAGE_SEGMENTATION_MODE",
    )
    platform_commission_rate: float = Field(
        default=0.15, alias="PLATFORM_COMMISSION_RATE"
    )
    clamav_host: str | None = Field(default=None, alias="CLAMAV_HOST")
    clamav_port: int = Field(default=3310, alias="CLAMAV_PORT")

    @field_validator("cors_allowed_origins")
    @classmethod
    def cors_origins_are_explicit(cls, value: str) -> str:
        """Reject wildcard CORS because refresh cookies use credentials."""
        origins = [origin.strip() for origin in value.split(",") if origin.strip()]
        if "*" in origins:
            raise ValueError("CORS_ALLOWED_ORIGINS cannot contain '*'.")
        return value

    @model_validator(mode="after")
    def production_totp_key_is_not_placeholder(self) -> Self:
        """Reject the dev TOTP encryption key outside local environments."""
        raw_totp_key = self.totp_encryption_key.get_secret_value()
        if (
            self.environment == "local"
            and raw_totp_key == PLACEHOLDER_TOTP_ENCRYPTION_KEY
        ):
            self.totp_encryption_key = SecretStr(DEV_TOTP_ENCRYPTION_KEY)
            return self
        if (
            self.environment != "local"
            and raw_totp_key
            in {DEV_TOTP_ENCRYPTION_KEY, PLACEHOLDER_TOTP_ENCRYPTION_KEY}
        ):
            raise ValueError("TOTP_ENCRYPTION_KEY must be set outside local.")
        return self

    @model_validator(mode="after")
    def production_payout_account_key_is_not_placeholder(self) -> Self:
        """Reject the dev payout-account encryption key outside local environments."""
        raw_key = self.payout_account_encryption_key.get_secret_value()
        if (
            self.environment == "local"
            and raw_key == PLACEHOLDER_PAYOUT_ACCOUNT_ENCRYPTION_KEY
        ):
            self.payout_account_encryption_key = SecretStr(
                DEV_PAYOUT_ACCOUNT_ENCRYPTION_KEY
            )
            return self
        if (
            self.environment != "local"
            and raw_key
            in {
                DEV_PAYOUT_ACCOUNT_ENCRYPTION_KEY,
                PLACEHOLDER_PAYOUT_ACCOUNT_ENCRYPTION_KEY,
            }
        ):
            raise ValueError("PAYOUT_ACCOUNT_ENCRYPTION_KEY must be set outside local.")
        return self

    @model_validator(mode="after")
    def production_partner_webhook_key_is_not_placeholder(self) -> Self:
        """Reject the dev partner-webhook encryption key outside local environments."""
        raw_key = self.partner_webhook_encryption_key.get_secret_value()
        if (
            self.environment == "local"
            and raw_key == PLACEHOLDER_PARTNER_WEBHOOK_ENCRYPTION_KEY
        ):
            self.partner_webhook_encryption_key = SecretStr(
                DEV_PARTNER_WEBHOOK_ENCRYPTION_KEY
            )
            return self
        if (
            self.environment != "local"
            and raw_key
            in {
                DEV_PARTNER_WEBHOOK_ENCRYPTION_KEY,
                PLACEHOLDER_PARTNER_WEBHOOK_ENCRYPTION_KEY,
            }
        ):
            raise ValueError(
                "PARTNER_WEBHOOK_ENCRYPTION_KEY must be set outside local."
            )
        return self

    @model_validator(mode="after")
    def production_secret_key_is_not_placeholder(self) -> Self:
        """Reject the dev SECRET_KEY outside local environments.

        SECRET_KEY signs JWT access tokens and the session_hint cookie used by
        the frontend middleware for routing. Shipping the dev value to staging
        or production lets any attacker forge tokens and hints.
        """
        if (
            self.environment != "local"
            and self.secret_key.get_secret_value()
            in {DEV_SECRET_KEY, PLACEHOLDER_SECRET_KEY}
        ):
            raise ValueError("SECRET_KEY must be set outside local.")
        return self

    @model_validator(mode="after")
    def production_provider_secrets_are_not_placeholders(self) -> Self:
        """Reject missing or placeholder payment secrets outside local.

        Phase 3 runs Stripe-only after the 2026-06-09 payment-scope decision.
        Staging/production should not boot with placeholder Stripe keys because
        webhook spoofing or failed settlement would become a financial integrity
        risk.
        """
        if self.environment == "local":
            return self

        provider_secrets = [
            self.stripe_secret_key,
            self.stripe_webhook_secret,
        ]
        if any(
            secret is None
            or secret.get_secret_value().strip() in {"", PLACEHOLDER_PROVIDER_SECRET}
            for secret in provider_secrets
        ):
            raise ValueError("Payment provider secrets must be set outside local.")
        return self

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a clean list."""
        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]

    @property
    def async_database_url(self) -> str:
        """Return a SQLAlchemy asyncpg-compatible database URL."""
        return _to_async_postgres_url(self.database_url)

    @property
    def sync_database_url(self) -> str:
        """Return a sync PostgreSQL URL for Alembic migrations."""
        return _to_sync_postgres_url(self.database_url)

    @property
    def celery_broker_url(self) -> str:
        """Use Redis database 0 for Celery broker traffic."""
        return _celery_redis_url(self.redis_url, 0)

    @property
    def celery_result_backend(self) -> str:
        """Use Redis database 0 for Celery result storage."""
        return _celery_redis_url(self.redis_url, 0)

    @property
    def cache_redis_url(self) -> str:
        """Use Redis database 0 for application cache, sessions, and rate limiting.

        Upstash serverless Redis supports only DB 0, so app traffic shares the
        Celery database. App keys are namespaced by domain prefixes (``refresh:``,
        ``rate_limit:``, ``email_verify:`` ...) and never collide with Celery's
        ``celery-task-meta-*``/``_kombu.*`` keyspace. Reuses the TLS-aware builder
        so ``rediss://`` (Upstash) carries ``ssl_cert_reqs``.
        """
        return _celery_redis_url(self.redis_url, 0)


@lru_cache
def get_settings() -> Settings:
    """Return cached process settings."""
    return Settings()
