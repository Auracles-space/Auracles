"""Async SQLAlchemy engine, session factory, and declarative base.

Defines the singleton `engine` connected to `settings.async_database_url`,
the `async_session_factory`, and `get_db()` — the FastAPI dependency that
yields a per-request `AsyncSession`. All ORM models inherit from `Base`.

Maps to: TDD Section 4 (database access layer).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings

settings = get_settings()


def create_database_engine(app_settings: Settings) -> AsyncEngine:
    """Build the application's async engine with explicit pool bounds.

    Left implicit, SQLAlchemy allows 5 connections plus 10 overflow per
    process; api, worker, and Beat together would then reserve up to 45
    against a managed Postgres tier that caps them. Sizing here — rather than
    at each call site — keeps every service on one policy that differs only by
    environment.

    Args:
        app_settings: Settings carrying the database URL and pool bounds.

    Returns:
        An async engine bounded to the configured pool size and overflow.
    """
    return create_async_engine(
        app_settings.async_database_url,
        pool_pre_ping=True,
        pool_size=app_settings.db_pool_size,
        max_overflow=app_settings.db_max_overflow,
    )


engine = create_database_engine(settings)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async database session for request handlers."""
    async with async_session_factory() as session:
        yield session
