"""Verify KYC status for a user in local/dev database.

Usage:
    uv run python -m scripts.verify_user_kyc <email>
"""

from __future__ import annotations

import sys
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import User


def verify_user_kyc(email: str) -> int:
    """Update user's kyc_status to 'verified'."""
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

    try:
        with Session(engine) as session:
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                print(f"Error: User with email '{email}' not found.")
                return 1

            user.kyc_status = "verified"
            session.commit()
            print(f"Successfully verified KYC for user '{email}' (user_id={user.id}).")
            return 0
    finally:
        engine.dispose()


def main() -> int:
    """CLI entrypoint."""
    if len(sys.argv) < 2:
        print("Usage: uv run python -m scripts.verify_user_kyc <email>")
        return 1

    email = sys.argv[1].strip().lower()
    return verify_user_kyc(email)


if __name__ == "__main__":
    raise SystemExit(main())
