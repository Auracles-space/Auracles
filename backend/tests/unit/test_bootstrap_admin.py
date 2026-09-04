"""Behavior tests for the local admin bootstrap command."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User, UserRole
from scripts.bootstrap_admin import BootstrapConfigError, bootstrap_admin
from tests.support.db_cleanup import clear_identity_state_sync


@pytest.fixture
def migrated_database() -> Iterator[None]:
    """Ensure auth tables exist for bootstrap tests."""
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    alembic_config = Config("alembic.ini")

    command.upgrade(alembic_config, "head")
    with Session(engine) as session:
        clear_identity_state_sync(session)
        session.commit()
    try:
        yield
    finally:
        with Session(engine) as session:
            clear_identity_state_sync(session)
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


def test_bootstrap_admin_refuses_to_promote_a_squatted_account(
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An account someone else registered at ADMIN_EMAIL must not gain admin.

    Registration creates the user row before the address is verified, so
    anyone may register the admin address ahead of the first bootstrap. If
    bootstrap then promoted whatever it found, it would hand superadmin to an
    account whose password only the squatter knows — it never rewrites an
    existing password. Refusing is the only safe branch; the operator can
    delete the row and re-run.
    """
    engine = create_engine(get_settings().sync_database_url, pool_pre_ping=True)
    with Session(engine) as session:
        session.add(
            User(
                email="dev@auracles.space",
                password_hash=hash_password("squatter-chosen-password"),
                display_name="Not The Admin",
                email_verified=False,
            )
        )
        session.commit()

    monkeypatch.setenv("ADMIN_EMAIL", "dev@auracles.space")
    monkeypatch.setenv("ADMIN_PASSWORD", "TheRealAdminPassword1")

    with pytest.raises(BootstrapConfigError):
        bootstrap_admin()

    with Session(engine) as session:
        squatter = session.scalar(
            select(User).where(User.email == "dev@auracles.space")
        )
        roles = session.scalars(
            select(UserRole).where(UserRole.user_id == squatter.id)
        ).all()

    engine.dispose()

    assert squatter.is_superadmin is False
    assert roles == []


def test_bootstrap_admin_requires_email_and_password(
    migrated_database: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bootstrap fails clearly when required admin environment is missing."""
    monkeypatch.delenv("ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)

    with pytest.raises(BootstrapConfigError):
        bootstrap_admin()
