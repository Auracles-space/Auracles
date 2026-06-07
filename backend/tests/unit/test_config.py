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
