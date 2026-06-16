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


def test_get_redis_decodes_responses_to_str(monkeypatch) -> None:
    """Redis must decode responses to str.

    Services cast stored values directly, e.g. ``UUID(str(user_id))`` in
    ``verify_email``/``reset_password``. Without ``decode_responses=True`` the
    client returns bytes, ``str(b'...')`` yields ``"b'...'"``, and UUID parsing
    raises ValueError -> HTTP 500 on email verification.
    """
    redis_module.get_redis.cache_clear()
    monkeypatch.setattr(
        redis_module,
        "get_settings",
        lambda: Settings(REDIS_URL="redis://localhost:6379/0"),
    )

    client = redis_module.get_redis()

    assert client.connection_pool.connection_kwargs["decode_responses"] is True

    redis_module.get_redis.cache_clear()
