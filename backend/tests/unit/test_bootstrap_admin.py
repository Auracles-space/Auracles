"""Behavior tests for the local admin bootstrap command."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import verify_password
from app.modules.auth.models import User, UserRole
from scripts.bootstrap_admin import BootstrapConfigError, bootstrap_admin


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for bootstrap tests."""
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    try:
        yield
    finally:
        with Session(engine) as session:
            session.execute(delete(UserRole))
            session.execute(delete(User))
            session.commit()
        engine.dispose()


def test_bootstrap_admin_creates_admin_user_once(
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap creates one verified admin account and is safe to re-run."""
    monkeypatch.setenv("ADMIN_EMAIL", "admin@auracles.space")
    monkeypatch.setenv("ADMIN_PASSWORD", "CorrectHorse9")

    first_result = bootstrap_admin()
    second_result = bootstrap_admin()

    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    with Session(engine) as session:
        users = session.scalars(
            select(User).where(User.email == "admin@auracles.space")
        )
        admin_user = users.one()
        roles = session.scalars(
            select(UserRole).where(UserRole.user_id == admin_user.id)
        ).all()

    engine.dispose()

    assert first_result.created is True
    assert second_result.created is False
    assert second_result.user_id == first_result.user_id
    assert admin_user.email_verified is True
    assert verify_password("CorrectHorse9", admin_user.password_hash or "")
    assert [role.role for role in roles] == ["admin"]


def test_bootstrap_admin_requires_email_and_password(
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap fails clearly when required admin environment is missing."""
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(BootstrapConfigError):
        bootstrap_admin()
