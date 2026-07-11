"""GDPR account anonymisation engine.

Applies irreversible tombstone mutations for scheduled deletion requests while
preserving financial and provenance-linked rows through the retained `users`
anchor record.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit
from app.core.security import decrypt_connector_token, hash_password
from app.integrations.google_drive import revoke_drive_token
from app.modules.auth.models import KycDocument, OAuthAccount, User, UserBackupCode
from app.modules.developer.models import ApiKey, DeveloperAccount
from app.modules.financials.models import PayoutAccount
from app.modules.gdpr.models import AccountDeletionRequest
from app.modules.gdpr.redaction import redact_metadata
from app.modules.integrations.models import OAuthConnection
from app.shared.models.audit_log import AuditLog

TOMBSTONE_DISPLAY_NAME = "Deleted user"


def _tombstone_email(user_id: UUID) -> str:
    """Return the irreversible tombstone email for one deleted user."""
    return f"deleted+{user_id}@tombstone.invalid"


def _tombstone_payout_lookup_hash(account_id: UUID) -> str:
    """Return a unique irreversible lookup hash for one tombstoned payout account."""
    return hashlib.sha256(f"deleted:{account_id}".encode()).hexdigest()


async def collect_kyc_object_keys(
    *,
    db: AsyncSession,
    user_id: UUID,
) -> list[str]:
    """Return KYC object keys that should be removed from private storage."""
    result = await db.execute(
        select(KycDocument.s3_key).where(KycDocument.user_id == user_id)
    )
    return [str(key) for key in result.scalars().all()]


async def anonymise_user_records(
    *,
    db: AsyncSession,
    user_id: UUID,
    request_id: UUID,
    completed_at: datetime,
) -> None:
    """Apply irreversible GDPR tombstone mutations inside one DB transaction."""
    user = await db.get(User, user_id, with_for_update=True)
    if user is None:
        raise ValueError("User not found.")

    deletion_request = await db.get(
        AccountDeletionRequest,
        request_id,
        with_for_update=True,
    )
    if deletion_request is None:
        raise ValueError("Account deletion request not found.")
    if deletion_request.status == "completed":
        return

    deleted_identity_fragments = (user.email, user.display_name)
    user.email = _tombstone_email(user.id)
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.display_name = TOMBSTONE_DISPLAY_NAME
    user.avatar_url = None
    user.bio = None
    user.location = None
    user.website = None
    user.stripe_customer_id = None
    user.kyc_status = "unverified"
    user.email_verified = False
    user.totp_secret = None
    user.totp_enabled = False
    user.deactivated_at = completed_at

    # Remove any org-library access rows tied to this user's staffed memberships.
    from app.modules.frameworks.models import LicenseGrant
    from app.modules.organizations.models import OrgMember, OrgTeamMember

    member_ids = list(
        (
            await db.execute(
                select(OrgMember.id)
                .where(OrgMember.user_id == user_id)
                .with_for_update()
            )
        ).scalars()
    )
    if member_ids:
        await db.execute(
            delete(LicenseGrant).where(LicenseGrant.member_id.in_(member_ids))
        )
        await db.execute(
            delete(OrgTeamMember).where(OrgTeamMember.member_id.in_(member_ids))
        )

    await db.execute(delete(OAuthAccount).where(OAuthAccount.user_id == user_id))
    await db.execute(delete(UserBackupCode).where(UserBackupCode.user_id == user_id))
    await db.execute(delete(KycDocument).where(KycDocument.user_id == user_id))
    connections = list(
        (
            await db.execute(
                select(OAuthConnection).where(OAuthConnection.user_id == user_id)
            )
        ).scalars()
    )
    for connection in connections:
        for encrypted_token in (
            connection.access_token_encrypted,
            connection.refresh_token_encrypted,
        ):
            if not encrypted_token:
                continue
            try:
                await revoke_drive_token(decrypt_connector_token(encrypted_token))
            except Exception:
                continue
    await db.execute(delete(OAuthConnection).where(OAuthConnection.user_id == user_id))

    payout_accounts = list(
        (
            await db.execute(
                select(PayoutAccount)
                .where(PayoutAccount.user_id == user_id)
                .with_for_update()
            )
        ).scalars()
    )
    for payout_account in payout_accounts:
        payout_account.deleted_at = completed_at
        payout_account.is_default = False
        payout_account.provider_account_id = f"deleted:{payout_account.id}"
        payout_account.provider_account_lookup_hash = _tombstone_payout_lookup_hash(
            payout_account.id
        )

    api_keys = list(
        (
            await db.execute(
                select(ApiKey)
                .join(
                    DeveloperAccount,
                    DeveloperAccount.id == ApiKey.developer_account_id,
                )
                .where(DeveloperAccount.user_id == user_id)
                .with_for_update()
            )
        ).scalars()
    )
    for api_key in api_keys:
        api_key.status = "revoked"
        api_key.revoked_at = completed_at

    audit_rows = list(
        (
            await db.execute(
                select(AuditLog)
                .where(
                    or_(
                        AuditLog.actor_id == user_id,
                        AuditLog.target_id == user_id,
                    )
                )
                .with_for_update()
            )
        ).scalars()
    )
    for audit_row in audit_rows:
        audit_row.metadata_ = redact_metadata(
            audit_row.metadata_ or {},
            blocked_fragments=deleted_identity_fragments,
        )
        audit_row.ip_address = None
        audit_row.user_agent = None

    deletion_request.status = "completed"
    deletion_request.blocked_reasons = []
    deletion_request.scheduled_for = None
    deletion_request.completed_at = completed_at

    await write_audit(
        db=db,
        actor_id=user_id,
        action="account_deletion_completed",
        target_type="account_deletion_request",
        target_id=deletion_request.id,
    )
