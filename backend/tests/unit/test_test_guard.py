"""Tests for the test-suite datastore guard.

The guard is the backstop that prevents the test suite from ever touching a
non-local datastore, even if `.env`/`ENV_FILE` is polluted with remote values.
"""

import pytest

from tests._guard import assert_local_datastores


def test_guard_passes_for_localhost() -> None:
    """Local DB and Redis hosts pass without raising."""
    assert_local_datastores(
        "postgresql+asyncpg://u:p@localhost:5432/db",
        "redis://127.0.0.1:6379/0",
    )


def test_guard_aborts_when_db_host_not_local() -> None:
    """A remote DATABASE_URL host is refused."""
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        assert_local_datastores(
            "postgresql+asyncpg://u:p@ep-cool.neon.tech/db",
            "redis://localhost:6379/0",
        )


def test_guard_aborts_when_redis_host_not_local() -> None:
    """A remote REDIS_URL host is refused."""
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        assert_local_datastores(
            "postgresql+asyncpg://u:p@localhost:5432/db",
            "rediss://default:pw@host.upstash.io:6379",
        )
