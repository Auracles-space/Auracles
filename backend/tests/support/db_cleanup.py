"""Shared test cleanup helpers for identity-linked rows.

Many backend tests create Users plus security-adjacent rows such as audit logs,
ledger entries, and KYC documents. These helpers delete the FK blockers before
user cleanup so fixtures remain order-independent across the full suite.

Anything gaining a foreign key to `users` must be added here. A missing table
does not fail loudly at the point of the mistake — it fails as a teardown
ForeignKeyViolation in whichever unrelated test happens to run next.
"""

from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.modules.auth.models import (
    IdentityVerification,
    KycDocument,
    User,
    UserRole,
)
from app.modules.financials.models import FinancialEvent
from app.modules.integrations.models import OAuthConnection
from app.modules.notifications.models import (
    Notification,
    NotificationDeliveryMarker,
)
from app.modules.organizations.models import Organization, OrgCapability, OrgMember
from app.shared.models.audit_log import AuditLog


async def clear_identity_state_async(session: AsyncSession) -> None:
    """Delete notification, ledger, audit, org, KYC, role, and user rows.

    Ordered so every foreign key to `users` is cleared before the users are.
    """
    await session.execute(delete(NotificationDeliveryMarker))
    await session.execute(delete(Notification))
    await session.execute(delete(FinancialEvent))
    await session.execute(delete(AuditLog))
    await session.execute(delete(OrgCapability))
    await session.execute(delete(OrgMember))
    await session.execute(delete(Organization))
    await session.execute(delete(OAuthConnection))
    await session.execute(delete(IdentityVerification))
    await session.execute(delete(KycDocument))
    await session.execute(delete(UserRole))
    await session.execute(delete(User))


def clear_identity_state_sync(session: Session) -> None:
    """Delete notification, ledger, audit, org, KYC, role, and user rows.

    Ordered so every foreign key to `users` is cleared before the users are.
    """
    session.execute(delete(NotificationDeliveryMarker))
    session.execute(delete(Notification))
    session.execute(delete(FinancialEvent))
    session.execute(delete(AuditLog))
    session.execute(delete(OrgCapability))
    session.execute(delete(OrgMember))
    session.execute(delete(Organization))
    session.execute(delete(OAuthConnection))
    session.execute(delete(IdentityVerification))
    session.execute(delete(KycDocument))
    session.execute(delete(UserRole))
    session.execute(delete(User))
