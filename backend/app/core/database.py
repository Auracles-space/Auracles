"""Async SQLAlchemy engine, session factory, and declarative base.

Defines the singleton `engine` connected to `settings.async_database_url`,
the `async_session_factory`, and `get_db()` — the FastAPI dependency that
yields a per-request `AsyncSession`. All ORM models inherit from `Base`.

Maps to: TDD Section 4 (database access layer).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.async_database_url, pool_pre_ping=True)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for SQLAlchemy models."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async database session for request handlers."""
    async with async_session_factory() as session:
        yield session
