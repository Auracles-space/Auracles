"""Connection pool sizing for the application and Beat database engines.

Both engines previously took SQLAlchemy's defaults (5 connections plus 10
overflow) per process. Across api, worker, and Beat that is up to 45
connections against a Neon tier that caps them, so the sizes have to be
explicit and per-service configurable.
"""

from __future__ import annotations

from app.core.config import Settings
from app.core.database import create_database_engine
from app.workers.schedules import create_beat_engine


def _settings(**overrides: object) -> Settings:
    """Build a Settings instance with pool overrides applied."""
    return Settings(
        DATABASE_URL="postgresql+asyncpg://user:pw@localhost:5432/auracles",
        SECRET_KEY="x" * 32,
        **overrides,  # type: ignore[arg-type]
    )


def test_application_engine_applies_configured_pool_bounds() -> None:
    """The async engine sizes its pool from settings rather than the defaults.

    An unbounded-by-default pool is the difference between one noisy service
    and every service losing its database connections at once.
    """
    engine = create_database_engine(
        _settings(DB_POOL_SIZE=4, DB_MAX_OVERFLOW=2),
    )

    assert engine.pool.size() == 4
    assert engine.pool._max_overflow == 2


def test_beat_engine_applies_configured_pool_bounds() -> None:
    """Beat's sync engine is pool-bounded too.

    Beat dispatches rather than queries, so it should hold the smallest pool of
    the three services; left at the defaults it reserves as many connections as
    the API.
    """
    engine = create_beat_engine(_settings(DB_POOL_SIZE=1, DB_MAX_OVERFLOW=1))

    assert engine.pool.size() == 1
    assert engine.pool._max_overflow == 1


def test_pool_defaults_stay_below_the_previous_implicit_total() -> None:
    """Shipping defaults must be safe when nothing sets the env vars.

    The failure mode being fixed is an unconfigured deploy, so the defaults
    themselves have to be conservative rather than relying on operators to
    override them.
    """
    settings = _settings()

    assert settings.db_pool_size == 5
    assert settings.db_max_overflow == 5
