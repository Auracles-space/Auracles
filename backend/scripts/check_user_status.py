"""Inspect user account, roles, and KYC document status in local database.

Usage:
    uv run python -m scripts.check_user_status <query>
"""

from __future__ import annotations

import sys
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.auth.models import User, KycDocument, UserRole


def check_user(query_str: str) -> int:
    settings = get_settings()
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

    try:
        with Session(engine) as session:
            stmt = select(User).where(
                (User.email.ilike(f"%{query_str}%")) | (User.display_name.ilike(f"%{query_str}%"))
            )
            users = list(session.scalars(stmt))

            if not users:
                print(f"No users found matching query '{query_str}'")
                return 1

            for user in users:
                print("=" * 60)
                print(f"USER RECORD:")
                print(f"  ID:           {user.id}")
                print(f"  Email:        {user.email}")
                print(f"  Display Name: {user.display_name}")
                print(f"  KYC Status:   {user.kyc_status}")
                print(f"  Email Verif:  {user.email_verified}")

                # Query roles
                roles_stmt = select(UserRole).where(UserRole.user_id == user.id)
                roles = list(session.scalars(roles_stmt))
                role_names = [r.role for r in roles]
                print(f"  Roles:        {role_names}")

                # Query associated KYC documents
                docs_stmt = select(KycDocument).where(KycDocument.user_id == user.id)
                docs = list(session.scalars(docs_stmt))

                print(f"KYC DOCUMENTS ({len(docs)}):")
                if not docs:
                    print("  No KYC documents uploaded.")
                for doc in docs:
                    print(f"  - Document ID:  {doc.id}")
                    print(f"    Doc Type:     {doc.doc_type}")
                    print(f"    Status:       {doc.status}")
                    print(f"    S3 Key:       {doc.s3_key}")
                    print(f"    Mime Type:    {doc.mime_type}")
                    print(f"    File Size:    {doc.file_size} bytes")
                    print(f"    Reviewed At:  {doc.reviewed_at}")
                    print(f"    Notes:        {doc.notes}")
            print("=" * 60)
            return 0
    finally:
        engine.dispose()


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: uv run python -m scripts.check_user_status <query>")
        return 1
    return check_user(sys.argv[1])


if __name__ == "__main__":
    raise SystemExit(main())
