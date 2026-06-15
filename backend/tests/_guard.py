"""Datastore guard for the test suite.

Refuses to run tests against a non-local database or Redis host. This is a
backstop behind the conftest env pin: even if `.env`/`ENV_FILE` carries remote
production values, the suite must never connect to production datastores.
"""

from urllib.parse import urlsplit

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def assert_local_datastores(database_url: str, redis_url: str) -> None:
    """Raise ``RuntimeError`` if either datastore host is not local.

    Args:
        database_url: Resolved application database URL.
        redis_url: Resolved application Redis URL.

    Raises:
        RuntimeError: If the DB or Redis host is not a recognized local host.
    """
    for label, url in (("DATABASE_URL", database_url), ("REDIS_URL", redis_url)):
        host = urlsplit(url).hostname
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(
                f"Refusing to run tests against non-local {label} host {host!r}."
            )
