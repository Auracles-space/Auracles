"""Behavior tests for Redis client configuration."""

from app.core import redis as redis_module
from app.core.config import Settings


def test_get_redis_uses_application_cache_database(monkeypatch) -> None:
    """Redis helper connects to database 0 (Upstash supports only DB 0)."""
    redis_module.get_redis.cache_clear()
    monkeypatch.setattr(
        redis_module,
        "get_settings",
        lambda: Settings(REDIS_URL="redis://localhost:6379/7"),
    )

    client = redis_module.get_redis()

    assert client.connection_pool.connection_kwargs["db"] == 0

    redis_module.get_redis.cache_clear()
