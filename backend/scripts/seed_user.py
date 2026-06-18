"""Seed an arbitrary user account for local/dev environments.

Companion to ``bootstrap_admin``: creates (or reuses) a verified user with a
chosen set of roles. Credentials and roles are supplied via environment
variables so no secret is ever hardcoded in the repo.

Run after ``alembic upgrade head``:

    SEED_EMAIL=... SEED_PASSWORD=... SEED_ROLES=operator \\
        uv run python -m scripts.seed_user

``SEED_ROLES`` is a comma-separated list of: contributor, operator, attestor,
admin. ``SEED_DISPLAY_NAME`` is optional (defaults to the email local part).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.modules.auth.models import User, UserRole

VALID_ROLES = {"contributor", "operator", "attestor", "admin"}


class SeedConfigError(RuntimeError):
    """Raised when required seed environment variables are missing or invalid."""


@dataclass(frozen=True)
class SeedResult:
    """Outcome of a seed attempt."""

    user_id: str
    created: bool
    roles_added: tuple[str, ...]


def _read_required_env(name: str) -> str:
    """Read a required environment variable and reject empty values."""
    value = os.getenv(name, "").strip()
    if not value:
        raise SeedConfigError(f"{name} is required.")
    return value


def _parse_roles(raw: str) -> tuple[str, ...]:
    """Parse and validate the comma-separated role list."""
    roles = tuple(
        dict.fromkeys(role.strip().lower() for role in raw.split(",") if role.strip())
    )
    if not roles:
        raise SeedConfigError("SEED_ROLES must list at least one role.")
    invalid = sorted(set(roles) - VALID_ROLES)
    if invalid:
        raise SeedConfigError(
            f"Unknown role(s): {', '.join(invalid)}. "
            f"Valid: {', '.join(sorted(VALID_ROLES))}."
        )
    return roles


def seed_user() -> SeedResult:
    """Create the seed user and attach the requested roles, idempotently."""
    email = _read_required_env("SEED_EMAIL").lower()
    password = _read_required_env("SEED_PASSWORD")
    roles = _parse_roles(_read_required_env("SEED_ROLES"))
    display_name = os.getenv("SEED_DISPLAY_NAME", "").strip() or email.split("@")[0]

    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

    try:
        with Session(engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(
                    email=email,
                    password_hash=hash_password(password),
                    display_name=display_name,
                    email_verified=True,
                )
                session.add(user)
                session.flush()
                created = True
            else:
                created = False

            existing = set(
                session.scalars(
                    select(UserRole.role).where(UserRole.user_id == user.id)
                )
            )
            added: list[str] = []
            for role in roles:
                if role not in existing:
                    session.add(UserRole(user_id=user.id, role=role))
                    added.append(role)

            session.commit()
            return SeedResult(
                user_id=str(user.id),
                created=created,
                roles_added=tuple(added),
            )
    finally:
        engine.dispose()


def main() -> int:
    """CLI entrypoint for ``uv run python -m scripts.seed_user``."""
    try:
        result = seed_user()
    except SeedConfigError as exc:
        print(str(exc))
        return 1

    action = "created" if result.created else "already_exists"
    roles = ",".join(result.roles_added) or "none"
    print(f"seed_user {action} user_id={result.user_id} roles_added={roles}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
