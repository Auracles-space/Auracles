"""Bootstrap the initial admin account.

This script is intentionally outside Alembic migrations because it creates
environment-dependent data. Run it after `alembic upgrade head` in a fresh
environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.modules.auth.models import User, UserRole


class BootstrapConfigError(RuntimeError):
    """Raised when the bootstrap environment is missing or unsafe to act on."""


@dataclass(frozen=True)
class BootstrapResult:
    """Result of attempting to ensure the initial admin exists."""

    user_id: str
    created: bool


def _read_required_env(name: str) -> str:
    """Read a required environment variable and reject empty values."""
    value = os.getenv(name, "").strip()
    if not value:
        raise BootstrapConfigError(f"{name} is required.")
    return value


def bootstrap_admin() -> BootstrapResult:
    """Create the initial admin user and role if they do not already exist."""
    admin_email = _read_required_env("ADMIN_EMAIL").lower()
    admin_password = _read_required_env("ADMIN_PASSWORD")
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

    try:
        with Session(engine) as session:
            user = session.scalar(select(User).where(User.email == admin_email))
            if user is None:
                user = User(
                    email=admin_email,
                    password_hash=hash_password(admin_password),
                    display_name="Auracles Admin",
                    email_verified=True,
                    is_superadmin=True,
                )
                session.add(user)
                session.flush()
                created = True
            else:
                # An account already holds this address. Promoting it blindly
                # would be a privilege-escalation path: registration creates
                # the user row before the address is verified, so anyone can
                # claim ADMIN_EMAIL ahead of the first bootstrap, and this
                # script never rewrites an existing password — the squatter
                # would end up a superadmin whose password only they know.
                #
                # Proving knowledge of ADMIN_PASSWORD is what distinguishes a
                # legitimate idempotent re-run from that. Refuse otherwise and
                # let a human decide; deleting the row and re-running is the
                # recovery.
                if not verify_password(admin_password, user.password_hash or ""):
                    raise BootstrapConfigError(
                        f"An account already exists for {admin_email} and its password "
                        "does not match ADMIN_PASSWORD. Refusing to grant it admin. "
                        "Investigate who registered it; if it is unwanted, delete the "
                        "user row and re-run."
                    )
                user.is_superadmin = True
                created = False

            role = session.scalar(
                select(UserRole).where(
                    UserRole.user_id == user.id,
                    UserRole.role == "admin",
                )
            )
            if role is None:
                session.add(UserRole(user_id=user.id, role="admin"))

            session.commit()
            return BootstrapResult(user_id=str(user.id), created=created)
    finally:
        engine.dispose()


def main() -> int:
    """CLI entrypoint for `uv run python -m scripts.bootstrap_admin`."""
    try:
        result = bootstrap_admin()
    except BootstrapConfigError as exc:
        print(str(exc))
        return 1

    action = "created" if result.created else "already_exists"
    print(f"admin_user {action} user_id={result.user_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
